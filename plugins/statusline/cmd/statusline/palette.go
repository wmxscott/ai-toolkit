package main

const (
	reset = "\x1b[0m"
	bold  = "\x1b[1m"
	dim   = "\x1b[2m"
	rgb   = "\x1b[38;2;"
)

type colour int

const (
	lavender colour = iota
	sky
	mint
	gold
	coral
	rose
	silver
	muted
	barOK
	barWarn
	barCrit
	vimNormal
	vimInsert
	vimVisual
	vimCommand
	effortLow
	effortMax
	numColours
)

type palette [numColours]string

// Catppuccin Macchiato
var dark = palette{
	lavender:   rgb + "183;189;248m",
	sky:        rgb + "145;215;227m",
	mint:       rgb + "166;218;149m",
	gold:       rgb + "238;212;159m",
	coral:      rgb + "245;169;127m",
	rose:       rgb + "238;153;160m",
	silver:     rgb + "165;173;203m",
	muted:      rgb + "110;115;141m",
	barOK:      rgb + "139;213;202m",
	barWarn:    rgb + "238;212;159m",
	barCrit:    rgb + "237;135;150m",
	vimNormal:  rgb + "138;173;244m",
	vimInsert:  rgb + "166;218;149m",
	vimVisual:  rgb + "198;160;246m",
	vimCommand: rgb + "237;135;150m",
	effortLow:  rgb + "125;196;228m",
	effortMax:  rgb + "237;135;150m",
}

// Catppuccin Latte
var light = palette{
	lavender:   rgb + "114;135;253m",
	sky:        rgb + "4;165;229m",
	mint:       rgb + "64;160;43m",
	gold:       rgb + "223;142;29m",
	coral:      rgb + "254;100;11m",
	rose:       rgb + "230;69;83m",
	silver:     rgb + "108;111;133m",
	muted:      rgb + "140;143;161m",
	barOK:      rgb + "23;146;153m",
	barWarn:    rgb + "223;142;29m",
	barCrit:    rgb + "210;15;57m",
	vimNormal:  rgb + "30;102;245m",
	vimInsert:  rgb + "64;160;43m",
	vimVisual:  rgb + "136;57;239m",
	vimCommand: rgb + "210;15;57m",
	effortLow:  rgb + "32;159;181m",
	effortMax:  rgb + "210;15;57m",
}

func paletteFor(theme string) (*palette, bool) {
	switch theme {
	case "dark":
		return &dark, true
	case "light":
		return &light, true
	}
	return nil, false
}

const (
	icoModel  = ""
	icoBolt   = ""
	icoDB     = ""
	icoClock  = "\U000f13ab"
	icoDollar = ""
	icoCal    = "\U000f1a32"
	icoVim    = ""
	icoGit    = ""
	icoBranch = ""
	icoStyle  = "\U000f150f"

	emDash = "—"
)

var circles = [...]string{"◯", "◔", "◑", "◕", "●"}

var efforts = [...]struct {
	level, label string
	colour       colour
}{
	{"low", "▁ low", effortLow},
	{"medium", "▂ med", gold},
	{"high", "▃ high", coral},
	{"xhigh", "▅ xhigh", rose},
	{"max", "█ max", effortMax},
}

var vimModes = [...]struct {
	mode   string
	colour colour
}{
	{"NORMAL", vimNormal},
	{"INSERT", vimInsert},
	{"VISUAL", vimVisual},
	{"V-LINE", vimVisual},
	{"V-BLOCK", vimVisual},
	{"COMMAND", vimCommand},
	{"REPLACE", coral},
}

var modelPrefixes = [...][2]string{
	{"Claude Opus", "Opus"},
	{"Claude Sonnet", "Sonnet"},
	{"Claude Haiku", "Haiku"},
}

// Skip huge untracked files when counting added lines; they are almost never source.
const maxUntrackedBytes = 10 * 1024 * 1024
