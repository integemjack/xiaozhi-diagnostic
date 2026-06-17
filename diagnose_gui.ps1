# Xiaozhi Diagnostic Center - GUI
# Zero dependency: uses built-in .NET WinForms.
# Architecture: all heavy work runs in a background Runspace; the UI thread only
#               refreshes via a timer, so the window never freezes and can always be closed.
# Three tabs: 1) Connection  2) Conversation Health  3) Devices (LAN)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# ---------------- Shared state ----------------
$sync = [hashtable]::Synchronized(@{})
$sync.Queue   = New-Object System.Collections.Concurrent.ConcurrentQueue[object]
$sync.Cancel  = $false
$sync.Running = $false
$sync.State   = [hashtable]::Synchronized(@{})
$sync.ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$sync.LastIpFile = Join-Path $sync.ScriptDir ".last_ip"
$sync.WsPort     = 8000
$sync.WebPort    = 8002
$sync.VisionPort = 8003
$sync.DbContainer= "xiaozhi-esp32-server-db"
$sync.DbUser     = "root"
$sync.DbPass     = "123456"
$sync.DbName     = "xiaozhi_esp32_server"
$sync.Containers = @("xiaozhi-esp32-server","xiaozhi-esp32-server-web","xiaozhi-esp32-server-db","xiaozhi-esp32-server-redis")

# ---------------- Colors / Fonts ----------------
$ColBg      = [System.Drawing.Color]::FromArgb(245,247,250)
$ColCard    = [System.Drawing.Color]::White
$ColHeader  = [System.Drawing.Color]::FromArgb(33,46,71)
$ColAccent  = [System.Drawing.Color]::FromArgb(45,125,210)
$ColOk      = [System.Drawing.Color]::FromArgb(34,160,86)
$ColWarn    = [System.Drawing.Color]::FromArgb(214,158,20)
$ColErr     = [System.Drawing.Color]::FromArgb(206,58,58)
$ColGray    = [System.Drawing.Color]::FromArgb(140,148,160)
$ColText    = [System.Drawing.Color]::FromArgb(40,44,52)
$ColLogText = [System.Drawing.Color]::FromArgb(220,224,230)

$ColorMap = @{
    ok=$ColOk; warn=$ColWarn; err=$ColErr; accent=$ColAccent;
    gray=$ColGray; text=$ColText; log=$ColLogText; neutral=[System.Drawing.Color]::FromArgb(60,66,78)
}

$FontTitle  = New-Object System.Drawing.Font("Segoe UI",15,[System.Drawing.FontStyle]::Bold)
$FontSub    = New-Object System.Drawing.Font("Segoe UI",9)
$FontItem   = New-Object System.Drawing.Font("Segoe UI",10)
$FontItemB  = New-Object System.Drawing.Font("Segoe UI",10,[System.Drawing.FontStyle]::Bold)
$FontVerdict= New-Object System.Drawing.Font("Segoe UI",11,[System.Drawing.FontStyle]::Bold)
$FontBtn    = New-Object System.Drawing.Font("Segoe UI",10,[System.Drawing.FontStyle]::Bold)
$FontLog    = New-Object System.Drawing.Font("Consolas",9)
$FontTab    = New-Object System.Drawing.Font("Segoe UI",10)

# ---------------- Main window ----------------
$form = New-Object System.Windows.Forms.Form
$form.Text = "Xiaozhi Diagnostic Center"
$form.Size = New-Object System.Drawing.Size(1000,740)
$form.StartPosition = "CenterScreen"
$form.BackColor = $ColBg
$form.MinimumSize = New-Object System.Drawing.Size(880,660)

$header = New-Object System.Windows.Forms.Panel
$header.Dock = "Top"; $header.Height = 64; $header.BackColor = $ColHeader
$form.Controls.Add($header)

$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = "Xiaozhi Diagnostic Center"; $lblTitle.Font = $FontTitle
$lblTitle.ForeColor = [System.Drawing.Color]::White; $lblTitle.AutoSize = $true
$lblTitle.Location = New-Object System.Drawing.Point(20,10)
$header.Controls.Add($lblTitle)

$lblSubtitle = New-Object System.Windows.Forms.Label
$lblSubtitle.Text = "Connection diagnosis - Conversation health - LAN devices"
$lblSubtitle.Font = $FontSub; $lblSubtitle.ForeColor = [System.Drawing.Color]::FromArgb(180,195,220)
$lblSubtitle.AutoSize = $true; $lblSubtitle.Location = New-Object System.Drawing.Point(22,40)
$header.Controls.Add($lblSubtitle)

# Global Stop button + progress bar (shared, only one task runs at a time)
$btnStop = New-Object System.Windows.Forms.Button
$btnStop.Text = "Stop"; $btnStop.Font = $FontBtn
$btnStop.Size = New-Object System.Drawing.Size(80,32)
$btnStop.FlatStyle = "Flat"; $btnStop.FlatAppearance.BorderSize = 0
$btnStop.BackColor = $ColGray; $btnStop.ForeColor = [System.Drawing.Color]::White
$btnStop.Anchor = "Top,Right"; $btnStop.Enabled = $false
$btnStop.Location = New-Object System.Drawing.Point(($form.ClientSize.Width-100),16)
$header.Controls.Add($btnStop)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Size = New-Object System.Drawing.Size(280,12)
$progress.Anchor = "Top,Right"
$progress.Location = New-Object System.Drawing.Point(($form.ClientSize.Width-400),26)
$progress.Style = "Continuous"
$header.Controls.Add($progress)

# ---------------- Tab control ----------------
$tabs = New-Object System.Windows.Forms.TabControl
$tabs.Dock = "Fill"; $tabs.Font = $FontTab
$tabs.Padding = New-Object System.Drawing.Point(16,6)
$form.Controls.Add($tabs)
$tabs.BringToFront()

$tabConn = New-Object System.Windows.Forms.TabPage; $tabConn.Text = "  1. Connection  "; $tabConn.BackColor = $ColBg
$tabChat = New-Object System.Windows.Forms.TabPage; $tabChat.Text = "  2. Conversation Health  "; $tabChat.BackColor = $ColBg
$tabDev  = New-Object System.Windows.Forms.TabPage; $tabDev.Text  = "  3. Devices  "; $tabDev.BackColor = $ColBg
$tabs.TabPages.AddRange(@($tabConn,$tabChat,$tabDev))

function New-TopBar($parent) {
    $bar = New-Object System.Windows.Forms.Panel
    $bar.Dock = "Top"; $bar.Height = 50; $bar.BackColor = $ColBg
    $parent.Controls.Add($bar)
    return $bar
}
function New-ActionBtn($text,$x,$color,$width) {
    if (-not $width) { $width = 200 }
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text; $b.Font = $FontBtn
    $b.Size = New-Object System.Drawing.Size($width,36)
    $b.Location = New-Object System.Drawing.Point($x,8)
    $b.FlatStyle = "Flat"; $b.FlatAppearance.BorderSize = 0
    $b.BackColor = $color; $b.ForeColor = [System.Drawing.Color]::White
    $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    return $b
}

# ============ Tab 1: Connection ============
$connBar = New-TopBar $tabConn
$btnRun     = New-ActionBtn "Check Server" 12 $ColAccent 160
$btnMonitor = New-ActionBtn "Monitor Device Connection (45s)" 180 $ColOk 240
$btnMonitor.Enabled = $false
$connBar.Controls.Add($btnRun); $connBar.Controls.Add($btnMonitor)

$connVerdict = New-Object System.Windows.Forms.Panel
$connVerdict.Dock = "Bottom"; $connVerdict.Height = 64
$connVerdict.BackColor = [System.Drawing.Color]::FromArgb(60,66,78)
$tabConn.Controls.Add($connVerdict)
$lblConnVerdict = New-Object System.Windows.Forms.Label
$lblConnVerdict.Dock = "Fill"; $lblConnVerdict.Text = "  Click [Check Server] to start"
$lblConnVerdict.Font = $FontVerdict; $lblConnVerdict.ForeColor = [System.Drawing.Color]::White
$lblConnVerdict.TextAlign = "MiddleLeft"; $lblConnVerdict.Padding = New-Object System.Windows.Forms.Padding(14,0,14,0)
$connVerdict.Controls.Add($lblConnVerdict)

$connSplit = New-Object System.Windows.Forms.SplitContainer
$connSplit.Dock = "Fill"; $connSplit.SplitterWidth = 6; $connSplit.BackColor = $ColBg
$tabConn.Controls.Add($connSplit); $connSplit.BringToFront()

$checkList = New-Object System.Windows.Forms.FlowLayoutPanel
$checkList.Dock = "Fill"; $checkList.FlowDirection = "TopDown"
$checkList.WrapContents = $false; $checkList.AutoScroll = $true
$checkList.BackColor = $ColBg; $checkList.Padding = New-Object System.Windows.Forms.Padding(10,10,10,10)
$connSplit.Panel1.Controls.Add($checkList)

$logBox = New-Object System.Windows.Forms.RichTextBox
$logBox.Dock = "Fill"; $logBox.Font = $FontLog; $logBox.ReadOnly = $true
$logBox.BackColor = [System.Drawing.Color]::FromArgb(30,34,42)
$logBox.ForeColor = $ColLogText; $logBox.BorderStyle = "None"
$connSplit.Panel2.Controls.Add($logBox)
$logTitle = New-Object System.Windows.Forms.Label
$logTitle.Text = "  Detailed Log"; $logTitle.Dock = "Top"; $logTitle.Height = 26
$logTitle.Font = $FontItemB; $logTitle.ForeColor = $ColText; $logTitle.TextAlign = "MiddleLeft"
$logTitle.BackColor = [System.Drawing.Color]::FromArgb(230,234,240)
$connSplit.Panel2.Controls.Add($logTitle); $logTitle.BringToFront()

# ============ Tab 2: Conversation Health ============
$chatBar = New-TopBar $tabChat
$btnChat = New-ActionBtn "Analyze Conversation Logs" 12 $ColAccent 220
$chatBar.Controls.Add($btnChat)
$lblChatHint = New-Object System.Windows.Forms.Label
$lblChatHint.Text = "Scans recent server logs for conversation failures / disconnects / model errors"
$lblChatHint.Font = $FontSub; $lblChatHint.ForeColor = $ColGray; $lblChatHint.AutoSize = $true
$lblChatHint.Location = New-Object System.Drawing.Point(245,18)
$chatBar.Controls.Add($lblChatHint)

$chatVerdict = New-Object System.Windows.Forms.Panel
$chatVerdict.Dock = "Bottom"; $chatVerdict.Height = 64
$chatVerdict.BackColor = [System.Drawing.Color]::FromArgb(60,66,78)
$tabChat.Controls.Add($chatVerdict)
$lblChatVerdict = New-Object System.Windows.Forms.Label
$lblChatVerdict.Dock = "Fill"; $lblChatVerdict.Text = "  Click [Analyze Conversation Logs] to start"
$lblChatVerdict.Font = $FontVerdict; $lblChatVerdict.ForeColor = [System.Drawing.Color]::White
$lblChatVerdict.TextAlign = "MiddleLeft"; $lblChatVerdict.Padding = New-Object System.Windows.Forms.Padding(14,0,14,0)
$chatVerdict.Controls.Add($lblChatVerdict)

$chatSplit = New-Object System.Windows.Forms.SplitContainer
$chatSplit.Dock = "Fill"; $chatSplit.SplitterWidth = 6; $chatSplit.BackColor = $ColBg
$tabChat.Controls.Add($chatSplit); $chatSplit.BringToFront()

$chatList = New-Object System.Windows.Forms.FlowLayoutPanel
$chatList.Dock = "Fill"; $chatList.FlowDirection = "TopDown"
$chatList.WrapContents = $false; $chatList.AutoScroll = $true
$chatList.BackColor = $ColBg; $chatList.Padding = New-Object System.Windows.Forms.Padding(10,10,10,10)
$chatSplit.Panel1.Controls.Add($chatList)

$chatLog = New-Object System.Windows.Forms.RichTextBox
$chatLog.Dock = "Fill"; $chatLog.Font = $FontLog; $chatLog.ReadOnly = $true
$chatLog.BackColor = [System.Drawing.Color]::FromArgb(30,34,42)
$chatLog.ForeColor = $ColLogText; $chatLog.BorderStyle = "None"
$chatSplit.Panel2.Controls.Add($chatLog)
$chatLogTitle = New-Object System.Windows.Forms.Label
$chatLogTitle.Text = "  Key Log Lines"; $chatLogTitle.Dock = "Top"; $chatLogTitle.Height = 26
$chatLogTitle.Font = $FontItemB; $chatLogTitle.ForeColor = $ColText; $chatLogTitle.TextAlign = "MiddleLeft"
$chatLogTitle.BackColor = [System.Drawing.Color]::FromArgb(230,234,240)
$chatSplit.Panel2.Controls.Add($chatLogTitle); $chatLogTitle.BringToFront()

# ============ Tab 3: Devices ============
$devBar = New-TopBar $tabDev
$btnDev = New-ActionBtn "Scan LAN Devices" 12 $ColAccent 180
$devBar.Controls.Add($btnDev)
$lblDevHint = New-Object System.Windows.Forms.Label
$lblDevHint.Text = "Scans all devices on the same LAN and marks which ones are registered Xiaozhi devices"
$lblDevHint.Font = $FontSub; $lblDevHint.ForeColor = $ColGray; $lblDevHint.AutoSize = $true
$lblDevHint.Location = New-Object System.Drawing.Point(205,18)
$devBar.Controls.Add($lblDevHint)

$devStatus = New-Object System.Windows.Forms.Panel
$devStatus.Dock = "Bottom"; $devStatus.Height = 40
$devStatus.BackColor = [System.Drawing.Color]::FromArgb(60,66,78)
$tabDev.Controls.Add($devStatus)
$lblDevStatus = New-Object System.Windows.Forms.Label
$lblDevStatus.Dock = "Fill"; $lblDevStatus.Text = "  Click [Scan LAN Devices] to start"
$lblDevStatus.Font = $FontVerdict; $lblDevStatus.ForeColor = [System.Drawing.Color]::White
$lblDevStatus.TextAlign = "MiddleLeft"; $lblDevStatus.Padding = New-Object System.Windows.Forms.Padding(14,0,14,0)
$devStatus.Controls.Add($lblDevStatus)

$devGrid = New-Object System.Windows.Forms.ListView
$devGrid.Dock = "Fill"; $devGrid.View = "Details"; $devGrid.FullRowSelect = $true
$devGrid.GridLines = $true; $devGrid.Font = $FontItem; $devGrid.BackColor = $ColCard
[void]$devGrid.Columns.Add("Type",70)
[void]$devGrid.Columns.Add("IP Address",130)
[void]$devGrid.Columns.Add("MAC Address",150)
[void]$devGrid.Columns.Add("Xiaozhi",80)
[void]$devGrid.Columns.Add("Alias / Board",180)
[void]$devGrid.Columns.Add("Last Connected",170)
$tabDev.Controls.Add($devGrid)
$devGrid.BringToFront()

$form.Add_Shown({
    try { $connSplit.SplitterDistance = 470 } catch {}
    try { $chatSplit.SplitterDistance = 470 } catch {}
})

# ---------------- UI helpers ----------------
$script:checkItems = @{}
$script:chatItems  = @{}

function UI-AddItemTo($store,$panel,$id,$title) {
    $row = New-Object System.Windows.Forms.Panel
    $row.Size = New-Object System.Drawing.Size(440,46); $row.BackColor = $ColCard
    $row.Margin = New-Object System.Windows.Forms.Padding(0,0,0,8)
    $icon = New-Object System.Windows.Forms.Label
    $icon.Text = [char]0x25CB; $icon.Font = $FontItemB; $icon.ForeColor = $ColGray
    $icon.Size = New-Object System.Drawing.Size(36,46); $icon.TextAlign = "MiddleCenter"
    $icon.Location = New-Object System.Drawing.Point(4,0)
    $row.Controls.Add($icon)
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = $title; $lbl.Font = $FontItem; $lbl.ForeColor = $ColText
    $lbl.Size = New-Object System.Drawing.Size(395,46); $lbl.TextAlign = "MiddleLeft"
    $lbl.Location = New-Object System.Drawing.Point(42,0)
    $row.Controls.Add($lbl)
    $panel.Controls.Add($row)
    $store[$id] = @{ Icon=$icon; Label=$lbl; Title=$title }
}
function UI-SetItemIn($store,$id,$status,$detail) {
    $it = $store[$id]; if (-not $it) { return }
    switch ($status) {
        "ok"   { $it.Icon.Text = [char]0x2714; $it.Icon.ForeColor = $ColOk }
        "warn" { $it.Icon.Text = "!";          $it.Icon.ForeColor = $ColWarn }
        "err"  { $it.Icon.Text = [char]0x2718; $it.Icon.ForeColor = $ColErr }
        default{ $it.Icon.Text = [char]0x25CB; $it.Icon.ForeColor = $ColGray }
    }
    if ($detail) { $it.Label.Text = "$($it.Title)`n$detail"; $it.Label.Font = $FontSub }
}
function UI-LogTo($box,$text,$colorName) {
    $c = $ColorMap[$colorName]; if (-not $c) { $c = $ColLogText }
    $box.SelectionStart = $box.TextLength
    $box.SelectionColor = $c
    $box.AppendText("$text`r`n")
    $box.SelectionStart = $box.TextLength
    $box.ScrollToCaret()
}
function UI-VerdictTo($lbl,$panel,$text,$colorName) {
    $lbl.Text = "  $text"
    $c = $ColorMap[$colorName]; if (-not $c) { $c = $ColorMap["neutral"] }
    $panel.BackColor = $c
}

# ---------------- Timer: drain background messages ----------------
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 80
$timer.Add_Tick({
    $msg = $null
    while ($sync.Queue.TryDequeue([ref]$msg)) {
        switch ($msg.type) {
            "addItem"  { UI-AddItemTo $script:checkItems $checkList $msg.id $msg.title }
            "setItem"  { UI-SetItemIn $script:checkItems $msg.id $msg.status $msg.detail }
            "log"      { UI-LogTo $logBox $msg.text $msg.color }
            "verdict"  { UI-VerdictTo $lblConnVerdict $connVerdict $msg.text $msg.color }
            "clear"    { $checkList.Controls.Clear(); $script:checkItems = @{}; $logBox.Clear() }
            "chatAdd"     { UI-AddItemTo $script:chatItems $chatList $msg.id $msg.title }
            "chatSet"     { UI-SetItemIn $script:chatItems $msg.id $msg.status $msg.detail }
            "chatLog"     { UI-LogTo $chatLog $msg.text $msg.color }
            "chatVerdict" { UI-VerdictTo $lblChatVerdict $chatVerdict $msg.text $msg.color }
            "chatClear"   { $chatList.Controls.Clear(); $script:chatItems = @{}; $chatLog.Clear() }
            "devClear"  { $devGrid.Items.Clear() }
            "devRow"    {
                $it = New-Object System.Windows.Forms.ListViewItem($msg.kind)
                [void]$it.SubItems.Add($msg.ip)
                [void]$it.SubItems.Add($msg.mac)
                [void]$it.SubItems.Add($msg.isXz)
                [void]$it.SubItems.Add($msg.alias)
                [void]$it.SubItems.Add($msg.lastConn)
                if ($msg.isXz -eq "Yes") { $it.BackColor = [System.Drawing.Color]::FromArgb(225,245,232); $it.Font = $FontItemB }
                [void]$devGrid.Items.Add($it)
            }
            "devStatus" { UI-VerdictTo $lblDevStatus $devStatus $msg.text $msg.color }
            "progress" {
                if ($msg.style) { $progress.Style = $msg.style }
                if ($null -ne $msg.max) { $progress.Maximum = [int]$msg.max }
                if ($null -ne $msg.value) { $progress.Value = [Math]::Min([int]$msg.value,$progress.Maximum) }
            }
            "done" {
                $sync.Running = $false
                $btnRun.Enabled = $true
                $btnMonitor.Enabled = $msg.allowMonitor
                $btnChat.Enabled = $true
                $btnDev.Enabled = $true
                $btnStop.Enabled = $false
                $progress.Style = "Continuous"; $progress.Value = 0
            }
            "ask" {
                $btns = if ($msg.buttons) { $msg.buttons } else { "OKCancel" }
                $r = [System.Windows.Forms.MessageBox]::Show($msg.text, $msg.title, $btns, "Information")
                $sync.State["ask_$($msg.key)_ok"] = ($r -eq "OK" -or $r -eq "Yes")
                $sync.State["ask_$($msg.key)_done"] = $true
            }
        }
    }
})
$timer.Start()

# ---------------- Background worker ----------------
$worker = {
    param($sync,$mode)

    function Q($obj) { $sync.Queue.Enqueue($obj) }
    function QLog($t,$c)        { Q @{ type="log"; text=$t; color=$c } }
    function QAdd($id,$t)       { Q @{ type="addItem"; id=$id; title=$t } }
    function QSet($id,$s,$d)    { Q @{ type="setItem"; id=$id; status=$s; detail=$d } }
    function QVerdict($t,$c)    { Q @{ type="verdict"; text=$t; color=$c } }
    function CLog($t,$c)        { Q @{ type="chatLog"; text=$t; color=$c } }
    function CAdd($id,$t)       { Q @{ type="chatAdd"; id=$id; title=$t } }
    function CSet($id,$s,$d)    { Q @{ type="chatSet"; id=$id; status=$s; detail=$d } }
    function CVerdict($t,$c)    { Q @{ type="chatVerdict"; text=$t; color=$c } }
    function QProg($style,$max,$val) { Q @{ type="progress"; style=$style; max=$max; value=$val } }

    # Show a dialog (handled on the UI thread) and wait for the answer. Returns $true if OK/Yes.
    function Ask($key,$title,$text,$buttons) {
        $sync.State["ask_${key}_done"] = $false
        $sync.State["ask_${key}_ok"]   = $false
        Q @{ type="ask"; key=$key; title=$title; text=$text; buttons=$buttons }
        $waited = 0
        while (-not $sync.State["ask_${key}_done"]) {
            if ($sync.Cancel) { return $false }
            Start-Sleep -Milliseconds 150; $waited += 150
            if ($waited -gt 600000) { return $false }
        }
        return [bool]$sync.State["ask_${key}_ok"]
    }

    function Test-PortListening($port) {
        $n = netstat -an | Select-String -SimpleMatch ":$port "
        if (-not $n) { return $false }
        foreach ($line in $n) { if ($line -match "LISTENING") { return $true } }
        return $false
    }
    function Get-LanIps {
        $ips = @()
        $ipcfg = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
            $_.IPAddress -ne "127.0.0.1" -and $_.PrefixOrigin -ne "WellKnown"
        }
        foreach ($ip in $ipcfg) {
            $a = $ip.IPAddress
            if ($a -match "^192\.168\." -or $a -match "^10\." -or $a -match "^172\.(1[6-9]|2[0-9]|3[0-1])\.") { $ips += $a }
        }
        return ($ips | Select-Object -Unique)
    }

    try {
        if ($mode -eq "server") {
            Q @{ type="clear" }
            QProg "Marquee" $null $null
            QVerdict "Checking server..." "neutral"
            QLog "===== Server check started =====" "accent"

            QAdd "docker" "Docker status"
            $dockerOk = $false
            try { docker info *> $null; $dockerOk = ($LASTEXITCODE -eq 0) } catch { $dockerOk = $false }
            $sync.State["DockerOk"] = $dockerOk
            if ($dockerOk) { QSet "docker" "ok" "Docker is running"; QLog "[OK] Docker is running" "ok" }
            else { QSet "docker" "err" "Docker not running / not installed"; QLog "[FAIL] Docker is not running. Start Docker Desktop first." "err" }
            if ($sync.Cancel) { return }

            $running = @()
            if ($dockerOk) {
                try { $o = docker ps --format "{{.Names}}" 2>$null; if ($o) { $running = $o -split "`r?`n" | Where-Object { $_ -ne "" } } } catch {}
            }
            $allC = $true
            foreach ($c in $sync.Containers) {
                if ($sync.Cancel) { return }
                QAdd "c_$c" "Container: $c"
                if ($running -contains $c) { QSet "c_$c" "ok" "Running"; QLog "[OK] Container running: $c" "ok" }
                else { QSet "c_$c" "err" "Not running"; QLog "[FAIL] Container not running: $c" "err"; $allC = $false }
            }
            $sync.State["ContainersOk"] = $allC

            $portMap = @{ "$($sync.WsPort)"="WebSocket conversation"; "$($sync.WebPort)"="Web console / OTA"; "$($sync.VisionPort)"="Vision API" }
            $allP = $true
            foreach ($p in @($sync.WsPort,$sync.WebPort,$sync.VisionPort)) {
                if ($sync.Cancel) { return }
                QAdd "p_$p" "Port $p ($($portMap["$p"]))"
                if (Test-PortListening $p) { QSet "p_$p" "ok" "Listening"; QLog "[OK] Port $p is listening" "ok" }
                else { QSet "p_$p" "err" "Not listening"; QLog "[FAIL] Port $p is not listening" "err"; $allP = $false }
            }
            $sync.State["PortsOk"] = $allP

            # Detect LAN IP early (needed to build the correct OTA address)
            if ($sync.Cancel) { return }
            $lanIps = @(Get-LanIps)
            $sync.State["LanIps"] = $lanIps
            $serverIp = if ($lanIps.Count -gt 0) { ($lanIps | Where-Object { $_ -match "^192\.168\." } | Select-Object -First 1) } else { $null }
            if (-not $serverIp -and $lanIps.Count -gt 0) { $serverIp = $lanIps[0] }
            $otaAddr = if ($serverIp) { "http://${serverIp}:$($sync.WebPort)/xiaozhi/ota/" } else { "http://<server-ip>:$($sync.WebPort)/xiaozhi/ota/" }
            $sync.State["OtaAddr"] = $otaAddr

            # OTA endpoint check - the address the device must point to (trailing slash matters!)
            if ($sync.Cancel) { return }
            QAdd "ota" "OTA address for the device"
            $otaOk = $false; $wsAddr = $null; $noSlashDiffers = $false
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$($sync.WebPort)/xiaozhi/ota/" -TimeoutSec 5 -UseBasicParsing
                $otaOk = $true
                $body = $r.Content | Out-String
                $m = [regex]::Match($body, "ws://[^\s`"']+")
                if ($m.Success) { $wsAddr = $m.Value }
            } catch { if ($_.Exception.Response) { $otaOk = $true } }

            # Probe the WRONG variant (no trailing slash) to demonstrate the difference
            $noSlashCode = $null
            try {
                $r2 = Invoke-WebRequest -Uri "http://127.0.0.1:$($sync.WebPort)/xiaozhi/ota" -TimeoutSec 5 -UseBasicParsing -MaximumRedirection 0
                $noSlashCode = [int]$r2.StatusCode
            } catch {
                if ($_.Exception.Response) { $noSlashCode = [int]$_.Exception.Response.StatusCode }
            }
            if ($noSlashCode -ne 200) { $noSlashDiffers = $true }

            if ($otaOk) {
                QSet "ota" "ok" "Use: $otaAddr"
                QLog "[OK] OTA endpoint is alive." "ok"
                QLog "     >>> Device OTA address MUST be exactly:" "accent"
                QLog "         $otaAddr" "accent"
                QLog "     Note the trailing slash '/' at the end - it is REQUIRED." "warn"
                if ($noSlashDiffers) {
                    QLog "     Without the trailing slash (.../xiaozhi/ota) the server returned $noSlashCode, not 200 -" "warn"
                    QLog "     so a missing slash will make the device fail to get its config." "warn"
                }
                if ($wsAddr) { QLog "     (OTA will hand the device this WebSocket address: $wsAddr)" "gray"; $sync.State["OtaWsAddr"] = $wsAddr }
            } else {
                QSet "ota" "warn" "OTA not reachable locally"
                QLog "[WARN] OTA endpoint not reachable locally on port $($sync.WebPort)." "warn"
                QLog "     The device OTA address should be: $otaAddr (with trailing slash)" "warn"
            }
            $sync.State["OtaOk"] = $otaOk

            if ($sync.Cancel) { return }
            QAdd "ws" "WebSocket port connectivity"
            $wsReach = $false
            try { $t = Test-NetConnection -ComputerName "127.0.0.1" -Port $sync.WsPort -WarningAction SilentlyContinue; $wsReach = $t.TcpTestSucceeded } catch {}
            if ($wsReach) { QSet "ws" "ok" "Reachable locally"; QLog "[OK] WebSocket port reachable" "ok" }
            else { QSet "ws" "err" "Not reachable"; QLog "[FAIL] WebSocket port not reachable" "err" }
            $sync.State["WsReachable"] = $wsReach

            if ($sync.Cancel) { return }
            QAdd "ip" "Server IP vs database consistency"
            $ipText = if ($lanIps.Count -gt 0) { $lanIps -join ", " } else { "none" }
            QLog "Local LAN IP: $ipText" "gray"
            $dbIp = $null
            if (Test-Path $sync.LastIpFile) { $dbIp = (Get-Content $sync.LastIpFile -Raw).Trim() }
            $sync.State["DbIp"] = $dbIp
            if ($lanIps.Count -eq 0) {
                QSet "ip" "err" "No LAN IP on this machine"; QLog "[FAIL] This machine is not on a LAN." "err"; $sync.State["IpMatch"] = $false
            } elseif ($dbIp) {
                if ($lanIps -contains $dbIp) { QSet "ip" "ok" "DB IP $dbIp matches this machine"; QLog "[OK] Database IP matches: $dbIp" "ok"; $sync.State["IpMatch"] = $true }
                else {
                    QSet "ip" "err" "DB IP=$dbIp not among local IPs!"
                    QLog "[FAIL] Database IP ($dbIp) is not this machine's current IP ($ipText)!" "err"
                    QLog "       => Fix: run changeIp.bat and set it to $ipText" "warn"
                    $sync.State["IpMatch"] = $false
                    # Offer to open changeIp.bat right away
                    $askText = "The server IP in the database ($dbIp) does NOT match this machine's current IP ($ipText).`n`nDevices will receive a wrong WebSocket address and fail to connect.`n`nOpen changeIp.bat now to fix it?"
                    if (Ask "fixip" "IP Mismatch Detected" $askText "YesNo") {
                        $batPath = Join-Path $sync.ScriptDir "changeIp.bat"
                        if (Test-Path $batPath) {
                            try { Start-Process -FilePath $batPath -WorkingDirectory $sync.ScriptDir; QLog "       => Opened changeIp.bat. Follow its prompts, then re-run Check Server." "accent" }
                            catch { QLog "       => Failed to open changeIp.bat: $($_.Exception.Message)" "err" }
                        } else {
                            QLog "       => changeIp.bat not found in $($sync.ScriptDir)" "err"
                        }
                    }
                }
            } else { QSet "ip" "warn" ".last_ip not found, skipped"; QLog "[WARN] .last_ip file not found." "warn"; $sync.State["IpMatch"] = $null }

            if ($sync.Cancel) { return }
            QAdd "fw" "Windows Firewall"
            $fwOn = 0
            try { $fwOn = @(Get-NetFirewallProfile -ErrorAction SilentlyContinue | Where-Object { $_.Enabled }).Count } catch {}
            if ($fwOn -gt 0) { QSet "fw" "warn" "Enabled ($fwOn profiles)"; QLog "[WARN] Firewall is on, may block devices." "warn"; $sync.State["FirewallOn"] = $true }
            else { QSet "fw" "ok" "Disabled"; QLog "[OK] Firewall is disabled." "ok"; $sync.State["FirewallOn"] = $false }

            QLog "===== Server check complete =====" "accent"
            $st = $sync.State
            if (-not $st["DockerOk"] -or -not $st["ContainersOk"] -or -not $st["PortsOk"] -or ($st["WsReachable"] -eq $false)) {
                QVerdict "Server not ready: service/port problem. Run docker_port_fix.bat first." "err"
            } elseif ($st["IpMatch"] -eq $false) {
                QVerdict "Services OK, but DATABASE IP is wrong. Run changeIp.bat to set it to this machine's IP." "warn"
            } elseif ($st["FirewallOn"]) {
                QVerdict "Server mostly OK, but firewall is on. If devices can't connect, run docker_port_fix.bat." "warn"
            } else {
                QVerdict "Server is all good! Device OTA address: $($sync.State['OtaAddr'])  (keep the trailing slash). Next: reboot the device, then click [Monitor Device Connection]." "ok"
            }
            Q @{ type="done"; allowMonitor=$true }
        }
        elseif ($mode -eq "monitor") {
            # Step 1: ask the user to TURN OFF the device
            $offText = "Step 1 of 2`n`nPlease TURN OFF (power off) the Xiaozhi device now.`n`nWhen it is fully off, click [OK] and monitoring will start."
            if (-not (Ask "off" "Step 1: Turn OFF the device" $offText "OKCancel")) {
                QLog "Monitoring cancelled." "gray"; Q @{ type="done"; allowMonitor=$true }; return
            }

            # Start monitoring
            QLog "" "gray"; QLog "===== Monitoring device connections (45s) =====" "accent"
            QVerdict "Monitoring... now turn the device ON" "neutral"
            QAdd "m_in"  "Capture inbound device connection"
            QAdd "m_ota" "Device reached OTA endpoint"
            QAdd "m_ws"  "Device established WebSocket"

            # Step 2: ask the user to TURN ON the device (monitoring already running)
            $onText = "Step 2 of 2`n`nMonitoring has started.`n`nNow TURN ON (power on) the Xiaozhi device so it connects to the server.`n`nClick [OK] to continue (monitoring runs for 45 seconds)."
            [void](Ask "on" "Step 2: Turn ON the device" $onText "OK")

            $myIps = @($sync.State["LanIps"]) + @("127.0.0.1","0.0.0.0")
            $sawIn = $false
            $inIps = New-Object System.Collections.ArrayList
            $total = 45
            QProg "Continuous" $total 0
            for ($e = 0; $e -lt $total; $e++) {
                if ($sync.Cancel) { QLog "Monitoring stopped." "gray"; Q @{ type="done"; allowMonitor=$true }; return }
                $conns = netstat -an | Select-String "ESTABLISHED|SYN_RECEIVED"
                foreach ($line in $conns) {
                    $m = [regex]::Match($line.ToString(), "(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)")
                    if ($m.Success) {
                        $lp = $m.Groups[2].Value; $rip = $m.Groups[3].Value
                        if (@("$($sync.WsPort)","$($sync.WebPort)","$($sync.VisionPort)") -contains $lp -and ($myIps -notcontains $rip) -and $rip -ne "0.0.0.0") {
                            if (-not $sawIn) { QLog "[FOUND] Inbound device connection: $rip -> local:$lp" "ok" }
                            $sawIn = $true
                            if ($inIps -notcontains $rip) { [void]$inIps.Add($rip) }
                        }
                    }
                }
                QProg $null $null ($e+1)
                Start-Sleep -Seconds 1
            }
            if ($sawIn) { QSet "m_in" "ok" "From: $($inIps -join ', ')" }
            else { QSet "m_in" "err" "No device connected"; QLog "[RESULT] No device connected during monitoring." "warn" }

            $sawOta=$false; $sawWs=$false; $authIssue=$false
            $devIds = New-Object System.Collections.ArrayList
            if ($sync.State["DockerOk"]) {
                try {
                    $sl = docker logs --since "60s" xiaozhi-esp32-server 2>&1 | Out-String
                    if ($sl -match "conn - Headers") { $sawWs = $true }
                    if ($sl -match "OTA.*device|device.*OTA|MQTT") { $sawOta = $true }
                    if ($sl -match "AuthenticationError|need_bind|bind") { $authIssue = $true }
                    $ids = [regex]::Matches($sl, "device-id'?\s*[:=]\s*'?([0-9a-fA-F:\-]{6,})")
                    foreach ($i in $ids) { $v=$i.Groups[1].Value; if ($devIds -notcontains $v) { [void]$devIds.Add($v) } }
                    $wl = docker logs --since "60s" xiaozhi-esp32-server-web 2>&1 | Out-String
                    if ($wl -match "ota") { $sawOta = $true }
                } catch {}
            }
            if ($sawOta) { QSet "m_ota" "ok" "Device reached OTA"; QLog "[LOG] Device reached the OTA endpoint." "ok" }
            else { QSet "m_ota" $(if($sawIn){"warn"}else{"err"}) "No OTA access in logs" }
            if ($sawWs) { QSet "m_ws" "ok" "WebSocket established"; QLog "[LOG] Device established a WebSocket connection." "ok" }
            else { QSet "m_ws" "err" "No WebSocket in logs" }
            if ($devIds.Count -gt 0) { QLog "Connected device IDs: $($devIds -join ', ')" "gray" }

            QLog "===== Monitoring finished =====" "accent"
            $ip0 = if (@($sync.State["LanIps"]).Count) { @($sync.State["LanIps"])[0] } else { "<server-ip>" }
            if ($sawWs) {
                if ($authIssue) { QVerdict "Device connected! But there were auth/bind messages. Bind the device at http://${ip0}:$($sync.WebPort)" "warn" }
                else { QVerdict "Device connected to WebSocket successfully. Network and server are fine. If still unusable, check the Conversation Health tab." "ok" }
            } elseif ($sawOta -or $sawIn) {
                # Device was detected on the network - no OTA alert needed
                QLog "[OK] Device detected on the network." "ok"
                QLog "     Connection appears to be working. If device still not responding, check Conversation Health tab." "gray"
                QVerdict "Device detected! Connection appears OK. If device still not responding, check Conversation Health tab." "ok"
            } else {
                # No device reached the server at all. The most common cause is a wrong OTA
                # address on the device (wrong IP/port, or missing the trailing slash).
                $otaAddr = $sync.State["OtaAddr"]
                if (-not $otaAddr) {
                    $sip = $null
                    if (@($sync.State["LanIps"]).Count) { $sip = (@($sync.State["LanIps"]) | Where-Object { $_ -match "^192\.168\." } | Select-Object -First 1); if (-not $sip) { $sip = @($sync.State["LanIps"])[0] } }
                    $otaAddr = if ($sip) { "http://${sip}:$($sync.WebPort)/xiaozhi/ota/" } else { "http://<server-ip>:$($sync.WebPort)/xiaozhi/ota/" }
                }
                QLog "[RESULT] No device reached the server during monitoring." "err"
                QLog "     Most likely the device's OTA address is wrong. It MUST be exactly:" "accent"
                QLog "         $otaAddr" "accent"
                QLog "     Common mistakes: wrong IP, wrong port (must be $($sync.WebPort)), or missing the trailing slash '/'." "warn"
                QLog "     Other causes: device not on the same WiFi, or router AP/client isolation." "warn"
                $otaMsg = "No device connected during monitoring.`n`nThe #1 cause is a wrong OTA address on the device. It must be EXACTLY:`n`n$otaAddr`n`nCheck carefully:`n- IP must be this server's LAN IP`n- Port must be $($sync.WebPort)`n- Keep the trailing slash '/' at the end (.../xiaozhi/ota/)`n`nAlso confirm the device is on the SAME WiFi and the router has no AP/client isolation."
                [void](Ask "noconn_ota" "Check the Device OTA Address" $otaMsg "OK")
                QVerdict "No device connected! Check the device OTA address: $otaAddr (right IP, port $($sync.WebPort), keep the trailing slash). Also confirm same WiFi / no AP isolation." "err"
            }
            Q @{ type="done"; allowMonitor=$true }
        }

        elseif ($mode -eq "chat") {
            Q @{ type="chatClear" }
            QProg "Marquee" $null $null
            CVerdict "Analyzing conversation logs..." "neutral"
            try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

            $dockerOk = $false
            try { docker info *> $null; $dockerOk = ($LASTEXITCODE -eq 0) } catch {}
            if (-not $dockerOk) {
                CAdd "d" "Read server logs"; CSet "d" "err" "Docker not running"
                CVerdict "Docker is not running, cannot read logs. Start the services first." "err"
                Q @{ type="done"; allowMonitor=$false }; return
            }

            CLog "Fetching recent server logs..." "gray"
            $log = ""
            try { $log = docker logs --tail 600 xiaozhi-esp32-server 2>&1 | Out-String } catch {}
            if ([string]::IsNullOrWhiteSpace($log)) {
                CAdd "d" "Read server logs"; CSet "d" "err" "Log is empty"
                CVerdict "No logs found. The server may have just started, or the container name is wrong." "warn"
                Q @{ type="done"; allowMonitor=$false }; return
            }
            $lines = $log -split "`r?`n"
            CLog "Read $($lines.Count) log lines." "gray"

            # 1) Device connection
            if ($sync.Cancel) { Q @{ type="done"; allowMonitor=$false }; return }
            CAdd "conn" "Device connection"
            $connCount = @($lines | Select-String "conn - Headers").Count
            if ($connCount -gt 0) { CSet "conn" "ok" "$connCount recent connection(s)"; CLog "[OK] Detected $connCount device connection(s) (conn - Headers)." "ok" }
            else { CSet "conn" "warn" "No device connection in recent logs"; CLog "[WARN] No device connection in recent logs." "warn" }

            # 2) LLM
            if ($sync.Cancel) { Q @{ type="done"; allowMonitor=$false }; return }
            CAdd "llm" "LLM (large model) calls"
            $llmReq    = @($lines | Select-String "\[LLM|base_url=").Count
            # Specific, reliable markers (avoid broad false positives):
            $llmKeyErr = @($lines | Select-String "API key is not set|key is not set|check_model_key").Count
            $llmRunErr = @($lines | Select-String "LLM stream processing error|Error in response generation").Count
            if ($llmKeyErr -gt 0) {
                CSet "llm" "err" "An LLM api_key is NOT configured"
                CLog "[FAIL] An LLM model's api_key is not set (still a placeholder like 'your...')." "err"
                CLog "       Note: the server has several LLM entries (main chat + memory-summary model)." "warn"
                CLog "       Even one unfilled key triggers this. If chat still works, a SECONDARY model's key is missing." "warn"
                CLog "       Fix: Web console -> Model Config -> set a real api_key for every LLM you use." "warn"
                $sync.State["ChatLlmKey"] = $true
            } elseif ($llmRunErr -gt 0) {
                CSet "llm" "err" "$llmRunErr LLM runtime error(s)"
                CLog "[FAIL] LLM call failed at runtime (wrong/expired key, no quota, or network)." "err"
                CLog "       Fix: verify the main LLM's api_key, account balance/quota, and that the base_url is reachable." "warn"
                $sync.State["ChatLlmRun"] = $true
            } elseif ($llmReq -gt 0) {
                CSet "llm" "ok" "$llmReq call(s), no errors"; CLog "[OK] LLM called $llmReq time(s), no errors." "ok"
            } else {
                CSet "llm" "warn" "No recent LLM calls"; CLog "[WARN] No LLM calls found." "warn"
            }

            # 3) TTS
            if ($sync.Cancel) { Q @{ type="done"; allowMonitor=$false }; return }
            CAdd "tts" "TTS (text-to-speech)"
            $ttsOk = @($lines | Select-String "providers.tts.base").Count
            $ttsErr = @($lines | Select-String "tts.*ERROR|TTS.*ERROR|tts.*Exception").Count
            if ($ttsErr -gt 0) { CSet "tts" "err" "$ttsErr TTS error(s)"; CLog "[FAIL] TTS errors - the device will have no sound." "err" }
            elseif ($ttsOk -gt 0) { CSet "tts" "ok" "$ttsOk synthesis event(s)"; CLog "[OK] TTS synthesis activity: $ttsOk." "ok" }
            else { CSet "tts" "warn" "No recent TTS activity"; CLog "[WARN] No TTS synthesis found." "warn" }

            # 4) Audio out
            if ($sync.Cancel) { Q @{ type="done"; allowMonitor=$false }; return }
            CAdd "audio" "Audio sent to device (device speaks)"
            $sendAudio = @($lines | Select-String "sendAudioHandle|SentenceType").Count
            if ($sendAudio -gt 0) { CSet "audio" "ok" "$sendAudio audio push(es)"; CLog "[OK] Server pushed audio to the device ($sendAudio times)." "ok" }
            else { CSet "audio" "warn" "No recent audio push"; CLog "[WARN] No audio push found; the device may never have spoken." "warn" }

            # 5) Auto goodbye / idle disconnect (the key issue)
            if ($sync.Cancel) { Q @{ type="done"; allowMonitor=$false }; return }
            CAdd "bye" "Auto goodbye / idle disconnect"
            $byeHit = @($lines | Select-String "Time flies|end this conversation|reluctant").Count
            if ($byeHit -gt 0) {
                CSet "bye" "warn" "Auto goodbye detected ($byeHit)"
                CLog "[FOUND] The 'idle auto-goodbye' feature was triggered." "warn"
                CLog "        Symptom: device says a sad farewell (may show crying face) then disconnects." "warn"
                CLog "        This is NOT a fault! It is the normal behavior after ~120s idle." "warn"
                CLog "        Fix: Web console -> Parameters -> increase close_connection_no_voice_time," "warn"
                CLog "             or set end_prompt.enable = false, then restart the server container." "warn"
                $sync.State["ChatBye"] = $true
            } else { CSet "bye" "ok" "No auto goodbye recently"; CLog "[OK] No auto-goodbye disconnect detected." "ok" }

            # 6) Weather plugin
            if ($sync.Cancel) { Q @{ type="done"; allowMonitor=$false }; return }
            CAdd "weather" "Weather plugin"
            $wErr = @($lines | Select-String "get_weather.*ERROR|Failed to get weather|Authentication failed").Count
            if ($wErr -gt 0) {
                CSet "weather" "warn" "Weather key/host auth failed"
                CLog "[WARN] Weather plugin auth failed (wrong KEY/Token/Host). Weather queries fail; conversation unaffected." "warn"
                CLog "       Fix: Web console -> Plugins -> get_weather -> set correct QWeather api_key and api_host." "warn"
                $sync.State["ChatWeather"] = $true
            } else { CSet "weather" "ok" "No weather plugin errors"; CLog "[OK] No weather plugin errors." "ok" }

            # 7) Other errors
            if ($sync.Cancel) { Q @{ type="done"; allowMonitor=$false }; return }
            CAdd "errs" "Other errors / exceptions"
            $errLines = $lines | Select-String "-ERROR-|Traceback|Exception|timeout|TimeoutError" | Select-Object -Last 8
            $errCount = @($lines | Select-String "-ERROR-|Traceback|Exception").Count
            if ($errCount -gt 0) {
                CSet "errs" "warn" "$errCount error(s) in logs (see right)"
                CLog "----- Recent error lines -----" "accent"
                foreach ($el in $errLines) {
                    $t = $el.ToString()
                    if ($t.Length -gt 200) { $t = $t.Substring(0,200) + "..." }
                    CLog $t "err"
                }
            } else { CSet "errs" "ok" "No obvious errors"; CLog "[OK] No obvious errors/exceptions in logs." "ok" }

            CLog "===== Analysis complete =====" "accent"
            if ($sync.State["ChatBye"]) {
                CVerdict "Main finding: the 'crying then no response' is caused by the IDLE AUTO-GOODBYE, not a fault. Increase the idle timeout or disable the goodbye prompt." "warn"
            } elseif ($sync.State["ChatLlmKey"]) {
                CVerdict "An LLM api_key is not configured (placeholder 'your...'). Set a real key for every LLM model in the Web console -> Model Config." "err"
            } elseif ($sync.State["ChatLlmRun"]) {
                CVerdict "LLM calls failed at runtime. Check the main LLM's api_key, quota/balance, and network/base_url." "err"
            } elseif ($ttsErr -gt 0) {
                CVerdict "Main cause of failure: TTS synthesis errors, device has no sound. Check TTS config." "err"
            } elseif ($connCount -eq 0) {
                CVerdict "No recent device conversation. Use the Connection tab first to confirm the device can connect." "warn"
            } else {
                CVerdict "Conversation pipeline looks healthy (connection/LLM/TTS/audio all present). If problems persist, see the error lines on the right." "ok"
            }
            Q @{ type="done"; allowMonitor=$false }
        }
        elseif ($mode -eq "devices") {
            Q @{ type="devClear" }
            QProg "Marquee" $null $null
            Q @{ type="devStatus"; text="Scanning LAN devices..."; color="neutral" }
            try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

            $lanIps = @(Get-LanIps)
            if ($lanIps.Count -eq 0) {
                Q @{ type="devStatus"; text="No LAN IP on this machine, cannot scan. Make sure it is connected to the network."; color="err" }
                Q @{ type="done"; allowMonitor=$false }; return
            }
            $baseIp = $lanIps | Where-Object { $_ -match "^192\.168\." } | Select-Object -First 1
            if (-not $baseIp) { $baseIp = $lanIps[0] }
            $prefix = $baseIp -replace "\.\d+$",""
            Q @{ type="devStatus"; text="Scanning subnet $prefix.1-254, please wait..."; color="neutral" }

            # Query registered Xiaozhi devices from DB (for marking)
            $xzMap = @{}
            $dockerOk = $false
            try { docker info *> $null; $dockerOk = ($LASTEXITCODE -eq 0) } catch {}
            if ($dockerOk) {
                try {
                    $qExpr = "SELECT mac_address,IFNULL(alias,''),IFNULL(last_connected_at,''),IFNULL(board,'') FROM $($sync.DbName).ai_device"
                    $rows = docker exec $sync.DbContainer mysql "-u$($sync.DbUser)" "-p$($sync.DbPass)" -N -e $qExpr 2>$null
                    foreach ($r in @($rows)) {
                        if ([string]::IsNullOrWhiteSpace($r)) { continue }
                        $cols = $r -split "`t"
                        if ($cols.Count -ge 1 -and $cols[0]) {
                            $key = ($cols[0] -replace "-",":").ToLower().Trim()
                            $xzMap[$key] = @{
                                alias = if ($cols.Count -ge 2) { $cols[1] } else { "" }
                                last  = if ($cols.Count -ge 3) { $cols[2] } else { "" }
                                board = if ($cols.Count -ge 4) { $cols[3] } else { "" }
                            }
                        }
                    }
                } catch {}
            }
            $sync.State["XzCount"] = $xzMap.Count

            # Ping sweep (async)
            $pings = @()
            for ($i=1; $i -le 254; $i++) {
                $p = New-Object System.Net.NetworkInformation.Ping
                $pings += [PSCustomObject]@{ Ping=$p; Task=$p.SendPingAsync("$prefix.$i",300); Ip="$prefix.$i" }
            }
            $done = 0
            foreach ($pg in $pings) {
                if ($sync.Cancel) { break }
                try { [void]$pg.Task.Wait(500) } catch {}
                $done++
                if ($done % 16 -eq 0) { QProg "Continuous" 254 $done }
            }
            QProg "Continuous" 254 254

            # Read ARP table -> IP/MAC
            $ipMac = @{}
            try {
                $arp = arp -a 2>$null
                foreach ($l in $arp) {
                    $m = [regex]::Match($l, "(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2})")
                    if ($m.Success) {
                        $ip = $m.Groups[1].Value
                        $mac = ($m.Groups[2].Value -replace "-",":").ToLower()
                        if ($ip -like "$prefix.*") { $ipMac[$ip] = $mac }
                    }
                }
            } catch {}

            # Add this machine
            $selfMac = ""
            try {
                $na = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq "Up" } | Select-Object -First 1
                if ($na) { $selfMac = ($na.MacAddress -replace "-",":").ToLower() }
            } catch {}
            if ($baseIp -and $selfMac) { $ipMac[$baseIp] = $selfMac }

            $sorted = $ipMac.Keys | Sort-Object { [int]($_ -replace "^.*\.","") }
            $xzFound = 0
            foreach ($ip in $sorted) {
                if ($sync.Cancel) { break }
                $mac = $ipMac[$ip]
                $isXz = "No"; $alias=""; $last=""; $kind="Other"
                if ($xzMap.ContainsKey($mac)) {
                    $isXz = "Yes"; $xzFound++
                    $info = $xzMap[$mac]
                    $alias = if ($info.alias) { $info.alias } else { $info.board }
                    $last = $info.last
                    $kind = "Xiaozhi"
                }
                if ($ip -eq $baseIp) { $kind = "This PC"; if ($isXz -eq "No") { $alias = "(server / this PC)" } }
                Q @{ type="devRow"; kind=$kind; ip=$ip; mac=$mac; isXz=$isXz; alias=$alias; lastConn=$last }
            }

            # Registered-but-offline Xiaozhi devices
            foreach ($mac in $xzMap.Keys) {
                if ($sync.Cancel) { break }
                $online = $false
                foreach ($v in $ipMac.Values) { if ($v -eq $mac) { $online = $true; break } }
                if (-not $online) {
                    $info = $xzMap[$mac]
                    $alias = if ($info.alias) { $info.alias } else { $info.board }
                    Q @{ type="devRow"; kind="Xiaozhi"; ip="(offline)"; mac=$mac; isXz="Yes"; alias=$alias; lastConn=$info.last }
                }
            }

            $total = @($sorted).Count
            if ($xzMap.Count -eq 0) {
                Q @{ type="devStatus"; text="Scan complete: $total device(s) on the LAN. No registered Xiaozhi devices in DB (or Docker not running)." ; color="warn" }
            } else {
                Q @{ type="devStatus"; text="Scan complete: $total LAN device(s), $xzFound Xiaozhi online / $($xzMap.Count) registered. Green rows are Xiaozhi devices." ; color="ok" }
            }
            Q @{ type="done"; allowMonitor=$false }
        }
    } catch {
        Q @{ type="log"; text="Error: $($_.Exception.Message)"; color="err" }
        Q @{ type="chatLog"; text="Error: $($_.Exception.Message)"; color="err" }
        Q @{ type="devStatus"; text="Error: $($_.Exception.Message)"; color="err" }
        Q @{ type="done"; allowMonitor=$false }
    }
}

# ---------------- Background run management ----------------
$script:rs = $null
$script:ps = $null

function Start-Worker($mode) {
    if ($sync.Running) { return }
    try { if ($script:ps) { $script:ps.Dispose() } } catch {}
    try { if ($script:rs) { $script:rs.Dispose() } } catch {}
    $sync.Cancel = $false
    $sync.Running = $true
    $btnRun.Enabled = $false
    $btnMonitor.Enabled = $false
    $btnChat.Enabled = $false
    $btnDev.Enabled = $false
    $btnStop.Enabled = $true

    $script:rs = [RunspaceFactory]::CreateRunspace()
    $script:rs.ApartmentState = "STA"
    $script:rs.ThreadOptions = "ReuseThread"
    $script:rs.Open()
    $script:ps = [PowerShell]::Create()
    $script:ps.Runspace = $script:rs
    [void]$script:ps.AddScript($worker).AddArgument($sync).AddArgument($mode)
    [void]$script:ps.BeginInvoke()
}

$btnRun.Add_Click({ Start-Worker "server" })
$btnMonitor.Add_Click({ Start-Worker "monitor" })
$btnChat.Add_Click({ Start-Worker "chat" })
$btnDev.Add_Click({ Start-Worker "devices" })
$btnStop.Add_Click({ $sync.Cancel = $true; $btnStop.Enabled = $false })

$form.Add_FormClosing({
    $sync.Cancel = $true
    try { $timer.Stop() } catch {}
    try { if ($script:ps) { $script:ps.Stop(); $script:ps.Dispose() } } catch {}
    try { if ($script:rs) { $script:rs.Close(); $script:rs.Dispose() } } catch {}
})

# Startup hints
$sync.Queue.Enqueue(@{ type="log"; text="Tip: run this tool on the 'server' PC (the one with Docker)."; color="gray" })
$sync.Queue.Enqueue(@{ type="log"; text="1. Connection: click [Check Server] first, then [Monitor Device Connection]."; color="gray" })
$sync.Queue.Enqueue(@{ type="chatLog"; text="Click [Analyze Conversation Logs] to auto-detect conversation failures / auto-goodbye / model errors."; color="gray" })

[void]$form.ShowDialog()

# Final cleanup
try { $timer.Stop(); $timer.Dispose() } catch {}
try { if ($script:ps) { $script:ps.Dispose() } } catch {}
try { if ($script:rs) { $script:rs.Dispose() } } catch {}
$form.Dispose()
