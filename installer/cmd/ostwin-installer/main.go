package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/charmbracelet/huh"
	"github.com/charmbracelet/lipgloss"
	"github.com/igot-ai/os-twin/installer/internal/installer"
	"github.com/spf13/cobra"
	"golang.org/x/term"
)

var (
	version   = "dev"
	commit    = "none"
	date      = "unknown"
	sourceRef = ""
)

func main() {
	if err := newRootCommand().Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func newRootCommand() *cobra.Command {
	opts := installer.DefaultOptions()
	if sourceRef != "" {
		opts.Ref = sourceRef
	}

	cmd := &cobra.Command{
		Use:     "ostwin-installer",
		Short:   "Interactive installer for Ostwin Agent OS",
		Version: formatVersion(),
		Long: "Interactive installer for Ostwin Agent OS. It collects setup choices, " +
			"downloads the source archive when needed, then delegates to the native " +
			"Bash or PowerShell installer.",
		RunE: func(cmd *cobra.Command, args []string) error {
			if !opts.Yes {
				if !term.IsTerminal(int(os.Stdin.Fd())) {
					return errors.New("interactive mode requires a TTY; rerun with --yes for non-interactive install")
				}
				if err := runInteractive(&opts); err != nil {
					return err
				}
			}

			ctx, cancel := context.WithTimeout(cmd.Context(), 45*time.Minute)
			defer cancel()
			return installer.Run(ctx, opts, os.Stdout)
		},
	}

	flags := cmd.Flags()
	flags.BoolVarP(&opts.Yes, "yes", "y", false, "run non-interactively with current defaults")
	flags.BoolVar(&opts.DryRun, "dry-run", false, "print the native installer command without running it")
	flags.BoolVar(&opts.JSON, "json", false, "write dry-run output as JSON")
	flags.StringVar(&opts.InstallDir, "dir", opts.InstallDir, "installation directory")
	flags.StringVar(&opts.SourceDir, "source-dir", "", "existing Agent OS source tree to install from")
	flags.StringVar(&opts.WorkDir, "work-dir", "", "directory for downloaded source extraction")
	flags.StringVar(&opts.Repo, "repo", opts.Repo, "GitHub repository to download, owner/name")
	flags.StringVar(&opts.Ref, "ref", opts.Ref, "GitHub branch to download")
	flags.StringVar(&opts.ArchiveURL, "archive-url", "", "explicit source tar.gz URL")
	flags.BoolVar(&opts.KeepSource, "keep-source", false, "keep downloaded source after installation")
	flags.IntVar(&opts.Port, "port", opts.Port, "dashboard port")
	flags.StringVar(&opts.Profile, "profile", opts.Profile, "install profile: full, dashboard, minimal")
	flags.BoolVar(&opts.DashboardOnly, "dashboard-only", false, "install dashboard API and frontend only")
	flags.BoolVar(&opts.Channel, "channel", false, "install channel connector dependencies")
	flags.BoolVar(&opts.SearchEngine, "search-engine", false, "install the optional SearXNG search engine")
	flags.StringVar(&opts.SearchEngineMode, "search-engine-mode", opts.SearchEngineMode, "SearXNG install method: docker or local")
	flags.BoolVar(&opts.SkipOptional, "skip-optional", false, "skip optional components")
	flags.BoolVar(&opts.SyncSkills, "sync-skills", false, "force bundled skill copy and dashboard sync on existing installs")
	flags.BoolVar(&opts.NoOpenCodeConfig, "no-opencode-config", false, "skip writing OpenCode config")
	flags.BoolVar(&opts.NoStart, "no-start", false, "install without starting services")

	cmd.SetVersionTemplate("{{.Version}}\n")
	cmd.AddCommand(newVersionCommand())

	return cmd
}

func formatVersion() string {
	return fmt.Sprintf("%s (commit %s, built %s)", version, commit, date)
}

func newVersionCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print installer version metadata",
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Fprintln(cmd.OutOrStdout(), formatVersion())
		},
	}
}

func runInteractive(opts *installer.Options) error {
	titleStyle := lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("39"))
	mutedStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("245"))

	fmt.Println(titleStyle.Render("Ostwin Agent OS installer"))
	fmt.Println(mutedStyle.Render("Answer a few questions, then the native installer takes over."))
	fmt.Println()

	portValue := strconv.Itoa(opts.Port)
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewSelect[string]().
				Title("Install profile").
				Description("Full is recommended for normal workstations.").
				Options(
					huh.NewOption("Full workstation", "full"),
					huh.NewOption("Dashboard only", "dashboard"),
					huh.NewOption("Minimal / no service start", "minimal"),
				).
				Value(&opts.Profile),
			huh.NewInput().
				Title("Install directory").
				Description("The existing installer uses ~/.ostwin by default.").
				Value(&opts.InstallDir),
			huh.NewInput().
				Title("Dashboard port").
				Value(&portValue).
				Validate(validatePort),
		),
		huh.NewGroup(
			huh.NewConfirm().
				Title("Install channel connector dependencies?").
				Description("Telegram, Discord, and Slack integrations.").
				Value(&opts.Channel),
			huh.NewConfirm().
				Title("Install local search engine?").
				Description("Optional SearXNG runtime for local deep search.").
				Value(&opts.SearchEngine),
			huh.NewConfirm().
				Title("Skip optional tools?").
				Description("Useful for CI or minimal environments.").
				Value(&opts.SkipOptional),
			huh.NewConfirm().
				Title("Skip OpenCode config changes?").
				Description("Leave ~/.config/opencode untouched.").
				Value(&opts.NoOpenCodeConfig),
			huh.NewConfirm().
				Title("Install without starting services?").
				Description("You can start services manually later.").
				Value(&opts.NoStart),
		),
	)

	if err := form.Run(); err != nil {
		return err
	}

	if opts.SearchEngine {
		if opts.SearchEngineMode == "" {
			opts.SearchEngineMode = "docker"
		}
		modeForm := huh.NewForm(
			huh.NewGroup(
				huh.NewSelect[string]().
					Title("SearXNG install method").
					Description("Docker is isolated; local clones SearXNG and installs it into a Python venv.").
					Options(
						huh.NewOption("Docker", "docker"),
						huh.NewOption("Local source / venv", "local"),
					).
					Value(&opts.SearchEngineMode),
			),
		)
		if err := modeForm.Run(); err != nil {
			return err
		}
	}

	port, err := strconv.Atoi(portValue)
	if err != nil {
		return err
	}
	opts.Port = port
	return nil
}

func validatePort(value string) error {
	port, err := strconv.Atoi(value)
	if err != nil {
		return errors.New("port must be a number")
	}
	if port < 1 || port > 65535 {
		return errors.New("port must be between 1 and 65535")
	}
	return nil
}
