package main

import (
	"encoding/json"
	"os"
	"testing"
)

type pythonConstants struct {
	Reset             string                       `json:"reset"`
	Bold              string                       `json:"bold"`
	Dim               string                       `json:"dim"`
	Palettes          map[string]map[string]string `json:"palettes"`
	Icons             map[string]string            `json:"icons"`
	EmDash            string                       `json:"em_dash"`
	Circles           []string                     `json:"circles"`
	Efforts           map[string][2]string         `json:"efforts"`
	VimModes          map[string]string            `json:"vim_modes"`
	ModelPrefixes     [][2]string                  `json:"model_prefixes"`
	MaxUntrackedBytes int64                        `json:"max_untracked_bytes"`
}

var colourNames = map[string]colour{
	"lavender":    lavender,
	"sky":         sky,
	"mint":        mint,
	"gold":        gold,
	"coral":       coral,
	"rose":        rose,
	"silver":      silver,
	"muted":       muted,
	"bar_ok":      barOK,
	"bar_warn":    barWarn,
	"bar_crit":    barCrit,
	"vim_normal":  vimNormal,
	"vim_insert":  vimInsert,
	"vim_visual":  vimVisual,
	"vim_command": vimCommand,
	"effort_low":  effortLow,
	"effort_max":  effortMax,
}

func loadPythonConstants(t *testing.T) pythonConstants {
	t.Helper()
	raw, err := os.ReadFile("../../testdata/constants.json")
	if err != nil {
		t.Fatal(err)
	}
	var c pythonConstants
	if err := json.Unmarshal(raw, &c); err != nil {
		t.Fatal(err)
	}
	return c
}

func TestEscapesMatchPython(t *testing.T) {
	c := loadPythonConstants(t)
	if reset != c.Reset || bold != c.Bold || dim != c.Dim {
		t.Errorf("escapes = %q %q %q, want %q %q %q", reset, bold, dim, c.Reset, c.Bold, c.Dim)
	}
}

func TestPalettesMatchPython(t *testing.T) {
	c := loadPythonConstants(t)
	if len(colourNames) != int(numColours) {
		t.Fatalf("colourNames has %d entries, want %d", len(colourNames), numColours)
	}
	for theme, want := range c.Palettes {
		p, ok := paletteFor(theme)
		if !ok {
			t.Errorf("paletteFor(%q) missing", theme)
			continue
		}
		if len(want) != int(numColours) {
			t.Errorf("%s: Python has %d colours, Go has %d", theme, len(want), numColours)
		}
		for name, esc := range want {
			col, ok := colourNames[name]
			if !ok {
				t.Errorf("%s: unknown colour %q", theme, name)
				continue
			}
			if p[col] != esc {
				t.Errorf("%s.%s = %q, want %q", theme, name, p[col], esc)
			}
		}
	}
	if _, ok := paletteFor("solarized"); ok {
		t.Error("paletteFor accepted an unknown theme")
	}
}

func TestIconsMatchPython(t *testing.T) {
	c := loadPythonConstants(t)
	got := map[string]string{
		"model":  icoModel,
		"bolt":   icoBolt,
		"db":     icoDB,
		"clock":  icoClock,
		"dollar": icoDollar,
		"cal":    icoCal,
		"vim":    icoVim,
		"git":    icoGit,
		"branch": icoBranch,
		"style":  icoStyle,
	}
	if len(got) != len(c.Icons) {
		t.Errorf("Go has %d icons, Python has %d", len(got), len(c.Icons))
	}
	for name, want := range c.Icons {
		if got[name] != want {
			t.Errorf("icon %s = %q, want %q", name, got[name], want)
		}
	}
	if emDash != c.EmDash {
		t.Errorf("emDash = %q, want %q", emDash, c.EmDash)
	}
	if len(circles) != len(c.Circles) {
		t.Fatalf("circles = %q, want %q", circles, c.Circles)
	}
	for i, want := range c.Circles {
		if circles[i] != want {
			t.Errorf("circles[%d] = %q, want %q", i, circles[i], want)
		}
	}
}

func TestEffortsAndVimModesMatchPython(t *testing.T) {
	c := loadPythonConstants(t)
	if len(efforts) != len(c.Efforts) {
		t.Errorf("Go has %d efforts, Python has %d", len(efforts), len(c.Efforts))
	}
	for _, e := range efforts {
		want, ok := c.Efforts[e.level]
		if !ok || e.label != want[0] || e.colour != colourNames[want[1]] {
			t.Errorf("effort %q = (%q, %d), want %q", e.level, e.label, e.colour, want)
		}
	}
	if len(vimModes) != len(c.VimModes) {
		t.Errorf("Go has %d vim modes, Python has %d", len(vimModes), len(c.VimModes))
	}
	for _, m := range vimModes {
		want, ok := c.VimModes[m.mode]
		if !ok || m.colour != colourNames[want] {
			t.Errorf("vim mode %q = %d, want %q", m.mode, m.colour, want)
		}
	}
}

func TestModelPrefixesAndLimitsMatchPython(t *testing.T) {
	c := loadPythonConstants(t)
	if len(modelPrefixes) != len(c.ModelPrefixes) {
		t.Fatalf("modelPrefixes = %q, want %q", modelPrefixes, c.ModelPrefixes)
	}
	for i, want := range c.ModelPrefixes {
		if modelPrefixes[i] != want {
			t.Errorf("modelPrefixes[%d] = %q, want %q", i, modelPrefixes[i], want)
		}
	}
	if maxUntrackedBytes != c.MaxUntrackedBytes {
		t.Errorf("maxUntrackedBytes = %d, want %d", maxUntrackedBytes, c.MaxUntrackedBytes)
	}
}
