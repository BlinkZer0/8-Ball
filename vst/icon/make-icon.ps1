# Draws the eight-ball app icon (eight-ball-256.png, eight-ball-32.png) with GDI+; CMake turns them into the
# Standalone's and the VST3's icon (ICON_BIG / ICON_SMALL). Re-run after changing the look.
Add-Type -AssemblyName System.Drawing
function Draw-Ball([int]$size, [string]$out) {
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'; $g.TextRenderingHint = 'AntiAliasGridFit'
    $g.Clear([System.Drawing.Color]::Transparent)
    $pad = [Math]::Max(1, $size * 0.03)
    $d = $size - 2 * $pad
    # the ball: dark gradient with a highlight up-left
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddEllipse($pad, $pad, $d, $d)
    $brush = New-Object System.Drawing.Drawing2D.PathGradientBrush $path
    $brush.CenterPoint = New-Object System.Drawing.PointF ($size * 0.36), ($size * 0.3)
    $brush.CenterColor = [System.Drawing.Color]::FromArgb(255, 92, 97, 106)
    $brush.SurroundColors = @([System.Drawing.Color]::FromArgb(255, 6, 7, 8))
    $g.FillEllipse($brush, $pad, $pad, $d, $d)
    # gold rim
    $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(255, 217, 164, 65)), ([Math]::Max(1, $size * 0.03))
    $g.DrawEllipse($pen, $pad, $pad, $d, $d)
    # the white circle and the 8
    $r = $d * 0.5
    $cx = $size / 2; $cy = $size / 2
    $g.FillEllipse([System.Drawing.Brushes]::Ivory, $cx - $r / 2, $cy - $r / 2, $r, $r)
    $font = New-Object System.Drawing.Font ('Segoe UI', ($size * 0.3), [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment = 'Center'; $fmt.LineAlignment = 'Center'
    $g.DrawString('8', $font, [System.Drawing.Brushes]::Black, (New-Object System.Drawing.RectangleF 0, ($size * 0.01), $size, $size), $fmt)
    # gloss
    $gloss = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(50, 255, 255, 255))
    $g.TranslateTransform($size * 0.32, $size * 0.27); $g.RotateTransform(-30)
    $g.FillEllipse($gloss, -$size * 0.12, -$size * 0.065, $size * 0.24, $size * 0.13)
    $g.ResetTransform()
    $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    "wrote $out"
}
Draw-Ball 256 (Join-Path $PSScriptRoot 'eight-ball-256.png')
Draw-Ball 32 (Join-Path $PSScriptRoot 'eight-ball-32.png')
