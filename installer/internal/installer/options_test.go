package installer

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

func TestArchiveURLDefaultsToBranchArchive(t *testing.T) {
	got := ArchiveURL("igot-ai/os-twin", "main")
	want := "https://github.com/igot-ai/os-twin/archive/refs/heads/main.tar.gz"
	if got != want {
		t.Fatalf("ArchiveURL() = %q, want %q", got, want)
	}
}

func TestArchiveURLSupportsTags(t *testing.T) {
	got := ArchiveURL("igot-ai/os-twin", "v1.2.3")
	want := "https://github.com/igot-ai/os-twin/archive/refs/tags/v1.2.3.tar.gz"
	if got != want {
		t.Fatalf("ArchiveURL() = %q, want %q", got, want)
	}
}

func TestNormalizeAppliesProfiles(t *testing.T) {
	tests := []struct {
		name string
		in   Options
		want Options
	}{
		{
			name: "dashboard",
			in:   Options{Profile: "dashboard", Port: 3366, InstallDir: "/tmp/ostwin"},
			want: Options{Profile: "dashboard", Port: 3366, InstallDir: "/tmp/ostwin", DashboardOnly: true, SkipOptional: true, Repo: defaultRepo, Ref: defaultRef},
		},
		{
			name: "minimal",
			in:   Options{Profile: "minimal", Port: 3366, InstallDir: "/tmp/ostwin"},
			want: Options{Profile: "minimal", Port: 3366, InstallDir: "/tmp/ostwin", SkipOptional: true, NoStart: true, Repo: defaultRepo, Ref: defaultRef},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tt.in
			if err := got.Normalize(); err != nil {
				t.Fatalf("Normalize() error = %v", err)
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Fatalf("Normalize() = %#v, want %#v", got, tt.want)
			}
		})
	}
}

func TestBuildInvocationUsesNativeInstaller(t *testing.T) {
	root := t.TempDir()
	agentsDir := filepath.Join(root, ".agents")
	if err := os.MkdirAll(agentsDir, 0o755); err != nil {
		t.Fatal(err)
	}

	installerName := "install.sh"
	if runtime.GOOS == "windows" {
		installerName = "install.ps1"
	}
	if err := os.WriteFile(filepath.Join(agentsDir, installerName), []byte("test"), 0o755); err != nil {
		t.Fatal(err)
	}

	opts := Options{
		Yes:              true,
		InstallDir:       "/tmp/ostwin",
		Port:             8080,
		DashboardOnly:    true,
		Channel:          true,
		SearchEngine:     true,
		SkipOptional:     true,
		NoOpenCodeConfig: true,
		NoStart:          true,
	}
	invocation, err := BuildInvocation(root, opts)
	if err != nil {
		t.Fatalf("BuildInvocation() error = %v", err)
	}

	joined := strings.Join(invocation.Args, " ")
	if runtime.GOOS == "windows" {
		if invocation.Command != "pwsh" {
			t.Fatalf("Command = %q, want pwsh", invocation.Command)
		}
		for _, token := range []string{"-Yes", "-Dir", "/tmp/ostwin", "-SourceDir", root, "-Port", "8080", "-DashboardOnly", "-Channel", "-SkipOptional", "-NoStart"} {
			if !strings.Contains(joined, token) {
				t.Fatalf("Windows args missing %q in %q", token, joined)
			}
		}
		if len(invocation.Warnings) != 2 {
			t.Fatalf("Warnings = %#v, want 2 unsupported-option warnings", invocation.Warnings)
		}
		return
	}

	if invocation.Command != "bash" {
		t.Fatalf("Command = %q, want bash", invocation.Command)
	}
	for _, token := range []string{"--yes", "--dir", "/tmp/ostwin", "--source-dir", root, "--port", "8080", "--dashboard-only", "--channel", "--search-engine", "--skip-optional", "--no-opencode-config", "--no-start"} {
		if !strings.Contains(joined, token) {
			t.Fatalf("Unix args missing %q in %q", token, joined)
		}
	}
}
