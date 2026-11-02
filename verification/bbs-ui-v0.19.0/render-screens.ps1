param([string]$InputDirectory,[string]$OutputDirectory)
Add-Type -AssemblyName System.Drawing
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$font = New-Object System.Drawing.Font('MS Gothic',14,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)
$format = [System.Drawing.StringFormat]::GenericTypographic.Clone()
$format.FormatFlags = $format.FormatFlags -bor [System.Drawing.StringFormatFlags]::MeasureTrailingSpaces
foreach ($name in @('main-ja','market-ja','flight','warp-confirm','naws-50','naws-100','remote-main')) {
  $lines = [System.IO.File]::ReadAllLines((Join-Path $InputDirectory ($name+'.txt')))
  $columns = if ($name -eq 'naws-50') {50} elseif ($name -eq 'naws-100') {100} else {80}
  $bitmap = New-Object System.Drawing.Bitmap(($columns*8+24),($lines.Count*19+24))
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.Clear([System.Drawing.Color]::FromArgb(12,17,21))
  $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::SingleBitPerPixelGridFit
  for ($row=0;$row -lt $lines.Count;$row++) {
    $cell=0
    foreach ($ch in $lines[$row].ToCharArray()) {
      $graphics.DrawString([string]$ch,$font,[System.Drawing.Brushes]::Gainsboro,[single](12+$cell*8),[single](12+$row*19),$format)
      $cell += $(if ([int]$ch -ge 0x2E80) {2} else {1})
    }
  }
  $raw = [System.IO.File]::ReadAllText((Join-Path $InputDirectory ($name+'.ansi')))
  $frame = ($raw -split "`e\[2J")[-1]
  $rawLines = $frame -split "`n"
  for ($row=0;$row -lt $rawLines.Count;$row++) {
    $match = [regex]::Match($rawLines[$row],"`e\[32m([+*])")
    if ($match.Success) {
      $prefix = [regex]::Replace($rawLines[$row].Substring(0,$match.Index),"`e\[[0-9;]*[A-Za-z]",'').Replace("`r",'')
      $graphics.DrawString($match.Groups[1].Value,$font,[System.Drawing.Brushes]::Lime,[single](12+$prefix.Length*8),[single](12+$row*19),$format)
    }
  }
  $bitmap.Save((Join-Path $OutputDirectory ($name+'.png')),[System.Drawing.Imaging.ImageFormat]::Png)
  $graphics.Dispose();$bitmap.Dispose()
}
$font.Dispose();$format.Dispose()

