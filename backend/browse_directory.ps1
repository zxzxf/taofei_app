# 选择工作目录的 PowerShell 脚本
# 用 OpenFileDialog (ValidateNames=False hack) 实现现代文件夹选择对话框
# 输出选中目录路径，取消则输出空行

Add-Type -AssemblyName System.Windows.Forms

# DPI 感知 + Win32 窗口操作辅助
if (-not ("Win32Api" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public class Win32Api {
    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);

    [DllImport("kernel32.dll")]
    public static extern uint GetCurrentThreadId();
}

// 用前台窗口句柄包装 IWin32Window，让对话框以用户当前窗口为属主
public class WindowWrapper : IWin32Window {
    public WindowWrapper(IntPtr handle) { _handle = handle; }
    public IntPtr Handle { get { return _handle; } }
    private IntPtr _handle;
}
"@
}
[Win32Api]::SetProcessDPIAware() | Out-Null

[System.Windows.Forms.Application]::EnableVisualStyles()

# 获取前台窗口（用户正在操作的应用窗口），作为对话框的属主
$fgHwnd = [Win32Api]::GetForegroundWindow()
$owner = New-Object WindowWrapper $fgHwnd

# 用 AttachThreadInput 把前台窗口的线程附加到当前线程，
# 绕过 SetForegroundWindow 限制，确保对话框弹到最前面
$fgProcId = [uint32]0
$fgThreadId = [Win32Api]::GetWindowThreadProcessId($fgHwnd, [ref]$fgProcId)
$myThreadId = [Win32Api]::GetCurrentThreadId()
$attached = $false
if ($fgThreadId -ne 0 -and $fgThreadId -ne $myThreadId) {
    $attached = [Win32Api]::AttachThreadInput($myThreadId, $fgThreadId, $true)
}

$dlg = New-Object System.Windows.Forms.OpenFileDialog
$dlg.Title = '选择工作目录'
$dlg.ValidateNames = $false
$dlg.CheckFileExists = $false
$dlg.CheckPathExists = $false
$dlg.FileName = 'Folder Selection.'
$dlg.Filter = 'Folder|Folder'
$dlg.AddExtension = $false

$r = $dlg.ShowDialog($owner)

if ($attached) {
    [Win32Api]::AttachThreadInput($myThreadId, $fgThreadId, $false) | Out-Null
}

if ($r -eq [System.Windows.Forms.DialogResult]::OK) {
    Split-Path $dlg.FileName -Parent
} else {
    ''
}
