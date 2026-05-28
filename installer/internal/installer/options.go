package installer

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

const (
	defaultRepo = "igot-ai/os-twin"
	defaultRef  = "main"
	defaultPort = 3366
)

// Options captures the human-facing installer choices before they are mapped to
// the native Bash or PowerShell installer.
type Options struct {
	Yes              bool
	DryRun           bool
	JSON             bool
	InstallDir       string
	SourceDir        string
	WorkDir          string
	Repo             string
	Ref              string
	ArchiveURL       string
	KeepSource       bool
	Port             int
	Profile          string
	DashboardOnly    bool
	Channel          bool
	SearchEngine     bool
	SkipOptional     bool
	NoOpenCodeConfig bool
	NoStart          bool
}

type Invocation struct {
	Command  string   `json:"command"`
	Args     []string `json:"args"`
	Source   string   `json:"source"`
	Warnings []string `json:"warnings,omitempty"`
}

func DefaultOptions() Options {
	home, err := os.UserHomeDir()
	installDir := "~/.ostwin"
	if err == nil && home != "" {
		installDir = filepath.Join(home, ".ostwin")
	}

	return Options{
		InstallDir: installDir,
		Repo:       defaultRepo,
		Ref:        defaultRef,
		Port:       defaultPort,
		Profile:    "full",
	}
}

func (o *Options) Normalize() error {
	if o.Repo == "" {
		o.Repo = defaultRepo
	}
	if o.Ref == "" {
		o.Ref = defaultRef
	}
	if o.Port == 0 {
		o.Port = defaultPort
	}
	if o.InstallDir == "" {
		defaults := DefaultOptions()
		o.InstallDir = defaults.InstallDir
	}
	if o.Profile == "" {
		o.Profile = "full"
	}
	if o.Port < 1 || o.Port > 65535 {
		return fmt.Errorf("port must be between 1 and 65535, got %d", o.Port)
	}

	switch strings.ToLower(o.Profile) {
	case "full":
	case "dashboard":
		o.DashboardOnly = true
		o.SkipOptional = true
	case "minimal":
		o.SkipOptional = true
		o.NoStart = true
	default:
		return fmt.Errorf("unknown profile %q", o.Profile)
	}

	return nil
}

func ArchiveURL(repo, ref string) string {
	cleanRepo := strings.Trim(repo, "/")
	cleanRef := strings.TrimSpace(ref)
	if strings.HasPrefix(cleanRef, "refs/") {
		return fmt.Sprintf("https://github.com/%s/archive/%s.tar.gz", cleanRepo, cleanRef)
	}
	if strings.HasPrefix(cleanRef, "v") {
		return fmt.Sprintf("https://github.com/%s/archive/refs/tags/%s.tar.gz", cleanRepo, cleanRef)
	}
	return fmt.Sprintf("https://github.com/%s/archive/refs/heads/%s.tar.gz", cleanRepo, cleanRef)
}

func (o Options) ResolveSource(ctx context.Context, out io.Writer) (string, func(), error) {
	if strings.TrimSpace(o.SourceDir) != "" {
		root, err := filepath.Abs(o.SourceDir)
		if err != nil {
			return "", func() {}, err
		}
		return root, func() {}, validateNativeInstaller(root)
	}

	workDir := o.WorkDir
	cleanup := func() {}
	if workDir == "" {
		tmp, err := os.MkdirTemp("", "ostwin-installer-*")
		if err != nil {
			return "", cleanup, err
		}
		workDir = tmp
		cleanup = func() {
			if !o.KeepSource {
				_ = os.RemoveAll(tmp)
			}
		}
	} else if err := os.MkdirAll(workDir, 0o755); err != nil {
		return "", cleanup, err
	}

	url := o.ArchiveURL
	if url == "" {
		url = ArchiveURL(o.Repo, o.Ref)
	}
	if out != nil {
		fmt.Fprintf(out, "Downloading source archive: %s\n", url)
	}

	root, err := downloadAndExtract(ctx, url, workDir)
	if err != nil {
		cleanup()
		return "", func() {}, err
	}
	if err := validateNativeInstaller(root); err != nil {
		cleanup()
		return "", func() {}, err
	}
	return root, cleanup, nil
}

func BuildInvocation(root string, opts Options) (Invocation, error) {
	if strings.TrimSpace(root) == "" {
		return Invocation{}, errors.New("source root is required")
	}

	root, err := filepath.Abs(root)
	if err != nil {
		return Invocation{}, err
	}

	if runtime.GOOS == "windows" {
		return buildWindowsInvocation(root, opts)
	}
	return buildUnixInvocation(root, opts)
}

func Run(ctx context.Context, opts Options, out io.Writer) error {
	if err := opts.Normalize(); err != nil {
		return err
	}

	root, cleanup, err := opts.ResolveSource(ctx, out)
	if err != nil {
		return err
	}
	defer cleanup()

	invocation, err := BuildInvocation(root, opts)
	if err != nil {
		return err
	}

	if opts.DryRun {
		return writeDryRun(out, invocation, opts.JSON)
	}

	for _, warning := range invocation.Warnings {
		fmt.Fprintf(out, "warning: %s\n", warning)
	}

	cmd := exec.CommandContext(ctx, invocation.Command, invocation.Args...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func buildUnixInvocation(root string, opts Options) (Invocation, error) {
	script := filepath.Join(root, ".agents", "install.sh")
	if _, err := os.Stat(script); err != nil {
		return Invocation{}, fmt.Errorf("missing installer script %s: %w", script, err)
	}

	args := []string{script}
	if opts.Yes {
		args = append(args, "--yes")
	}
	args = append(args, "--dir", opts.InstallDir, "--source-dir", root, "--port", strconv.Itoa(opts.Port))
	if opts.DashboardOnly {
		args = append(args, "--dashboard-only")
	}
	if opts.Channel {
		args = append(args, "--channel")
	}
	if opts.SearchEngine {
		args = append(args, "--search-engine")
	}
	if opts.SkipOptional {
		args = append(args, "--skip-optional")
	}
	if opts.NoOpenCodeConfig {
		args = append(args, "--no-opencode-config")
	}
	if opts.NoStart {
		args = append(args, "--no-start")
	}

	return Invocation{Command: "bash", Args: args, Source: root}, nil
}

func buildWindowsInvocation(root string, opts Options) (Invocation, error) {
	script := filepath.Join(root, ".agents", "install.ps1")
	if _, err := os.Stat(script); err != nil {
		return Invocation{}, fmt.Errorf("missing installer script %s: %w", script, err)
	}

	args := []string{"-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script}
	if opts.Yes {
		args = append(args, "-Yes")
	}
	args = append(args, "-Dir", opts.InstallDir, "-SourceDir", root, "-Port", strconv.Itoa(opts.Port))
	if opts.DashboardOnly {
		args = append(args, "-DashboardOnly")
	}
	if opts.Channel {
		args = append(args, "-Channel")
	}
	if opts.SkipOptional {
		args = append(args, "-SkipOptional")
	}
	if opts.NoStart {
		args = append(args, "-NoStart")
	}

	warnings := []string{}
	if opts.SearchEngine {
		warnings = append(warnings, "--search-engine is currently supported only by the macOS/Linux installer")
	}
	if opts.NoOpenCodeConfig {
		warnings = append(warnings, "--no-opencode-config is currently supported only by the macOS/Linux installer")
	}

	return Invocation{Command: "pwsh", Args: args, Source: root, Warnings: warnings}, nil
}

func validateNativeInstaller(root string) error {
	if runtime.GOOS == "windows" {
		if _, err := os.Stat(filepath.Join(root, ".agents", "install.ps1")); err != nil {
			return fmt.Errorf("%s is not an Agent OS source tree: %w", root, err)
		}
		return nil
	}
	if _, err := os.Stat(filepath.Join(root, ".agents", "install.sh")); err != nil {
		return fmt.Errorf("%s is not an Agent OS source tree: %w", root, err)
	}
	return nil
}

func writeDryRun(out io.Writer, invocation Invocation, asJSON bool) error {
	if out == nil {
		out = io.Discard
	}
	if asJSON {
		encoder := json.NewEncoder(out)
		encoder.SetIndent("", "  ")
		return encoder.Encode(invocation)
	}

	fmt.Fprintf(out, "Source: %s\n", invocation.Source)
	fmt.Fprintf(out, "Command: %s %s\n", invocation.Command, shellJoin(invocation.Args))
	for _, warning := range invocation.Warnings {
		fmt.Fprintf(out, "Warning: %s\n", warning)
	}
	return nil
}

func downloadAndExtract(ctx context.Context, url, dest string) (string, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	request.Header.Set("User-Agent", "ostwin-installer")

	client := &http.Client{Timeout: 5 * time.Minute}
	response, err := client.Do(request)
	if err != nil {
		return "", err
	}
	defer response.Body.Close()

	if response.StatusCode < 200 || response.StatusCode > 299 {
		return "", fmt.Errorf("download failed: %s", response.Status)
	}

	gzipReader, err := gzip.NewReader(response.Body)
	if err != nil {
		return "", err
	}
	defer gzipReader.Close()

	tarReader := tar.NewReader(gzipReader)
	var topDir string
	for {
		header, err := tarReader.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return "", err
		}
		if header == nil || header.Name == "" {
			continue
		}

		cleanName := filepath.Clean(filepath.FromSlash(header.Name))
		if cleanName == "." || strings.HasPrefix(cleanName, "..") || filepath.IsAbs(cleanName) {
			return "", fmt.Errorf("unsafe archive path %q", header.Name)
		}

		parts := strings.Split(cleanName, string(os.PathSeparator))
		if topDir == "" && len(parts) > 0 {
			topDir = parts[0]
		}

		target := filepath.Join(dest, cleanName)
		if !isSubpath(dest, target) {
			return "", fmt.Errorf("archive path escapes destination: %q", header.Name)
		}

		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, header.FileInfo().Mode().Perm()); err != nil {
				return "", err
			}
		case tar.TypeReg, tar.TypeRegA:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return "", err
			}
			file, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, header.FileInfo().Mode().Perm())
			if err != nil {
				return "", err
			}
			_, copyErr := io.Copy(file, tarReader)
			closeErr := file.Close()
			if copyErr != nil {
				return "", copyErr
			}
			if closeErr != nil {
				return "", closeErr
			}
		case tar.TypeSymlink:
			if runtime.GOOS == "windows" {
				continue
			}
			if filepath.IsAbs(header.Linkname) || strings.Contains(header.Linkname, "..") {
				return "", fmt.Errorf("unsafe archive symlink %q -> %q", header.Name, header.Linkname)
			}
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return "", err
			}
			if err := os.Symlink(header.Linkname, target); err != nil && !errors.Is(err, os.ErrExist) {
				return "", err
			}
		}
	}

	if topDir == "" {
		return "", errors.New("archive did not contain files")
	}
	return filepath.Join(dest, topDir), nil
}

func isSubpath(root, target string) bool {
	cleanRoot, err := filepath.Abs(root)
	if err != nil {
		return false
	}
	cleanTarget, err := filepath.Abs(target)
	if err != nil {
		return false
	}
	rel, err := filepath.Rel(cleanRoot, cleanTarget)
	if err != nil {
		return false
	}
	return rel == "." || (!strings.HasPrefix(rel, "..") && !filepath.IsAbs(rel))
}

func shellJoin(args []string) string {
	quoted := make([]string, 0, len(args))
	for _, arg := range args {
		if arg == "" || strings.ContainsAny(arg, " \t\n\"'`$&;()[]{}<>|*") {
			quoted = append(quoted, strconv.Quote(arg))
			continue
		}
		quoted = append(quoted, arg)
	}
	return strings.Join(quoted, " ")
}
