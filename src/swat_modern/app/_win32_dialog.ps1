# Win32 IFileOpenDialog via C# COM interop — reliable folder/file picker.
# Usage:
#   powershell -ExecutionPolicy Bypass -File _win32_dialog.ps1 folder "Title" hwnd
#   powershell -ExecutionPolicy Bypass -File _win32_dialog.ps1 file   "Title" hwnd "Label|*.ext|Label2|*.ext2"
# Prints selected path to stdout (empty if cancelled).

param(
    [Parameter(Position=0)][string]$Mode = "folder",
    [Parameter(Position=1)][string]$Title = "Select",
    [Parameter(Position=2)][long]$Hwnd = 0,
    [Parameter(Position=3)][string]$Filter = ""
)

$csharp = @"
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
class FileOpenDialogRCW {}

[ComImport, Guid("42F85136-DB7E-439C-85F1-E4075D135FC8"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IFileDialog {
    [PreserveSig] int Show(IntPtr hwndOwner);
    void SetFileTypes(uint cFileTypes, IntPtr rgFilterSpec);
    void SetFileTypeIndex(uint iFileType);
    void GetFileTypeIndex(out uint piFileType);
    void Advise(IntPtr pfde, out uint pdwCookie);
    void Unadvise(uint dwCookie);
    void SetOptions(uint fos);
    void GetOptions(out uint pfos);
    void SetDefaultFolder(IntPtr psi);
    void SetFolder(IntPtr psi);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
    void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string pszName);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string pszText);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string pszLabel);
    void GetResult(out IShellItem ppsi);
    void AddPlace(IntPtr psi, int fdap);
    void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string pszDefaultExtension);
    void Close(int hr);
    void SetClientGuid(ref Guid guid);
    void ClearClientData();
    void SetFilter(IntPtr pFilter);
}

[ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellItem {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetParent(out IShellItem ppsi);
    void GetDisplayName(uint sigdnName,
        [MarshalAs(UnmanagedType.LPWStr)] out string ppszName);
    void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
    void Compare(IShellItem psi, uint hint, out int piOrder);
}

[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
struct COMDLG_FILTERSPEC {
    [MarshalAs(UnmanagedType.LPWStr)] public string pszName;
    [MarshalAs(UnmanagedType.LPWStr)] public string pszSpec;
}

public static class FilePicker {
    const uint FOS_PICKFOLDERS     = 0x00000020;
    const uint FOS_FORCEFILESYSTEM = 0x00000040;
    const uint SIGDN_FILESYSPATH   = 0x80058000;

    public static string Pick(bool pickFolder, string title, IntPtr hwnd,
                              string[] filterLabels, string[] filterSpecs) {
        IFileDialog dlg = (IFileDialog)new FileOpenDialogRCW();
        uint opts;
        dlg.GetOptions(out opts);
        opts |= FOS_FORCEFILESYSTEM;
        if (pickFolder) opts |= FOS_PICKFOLDERS;
        dlg.SetOptions(opts);
        dlg.SetTitle(title);

        // Set file type filters (file mode only)
        if (!pickFolder && filterLabels != null && filterLabels.Length > 0) {
            int n = filterLabels.Length;
            var specs = new COMDLG_FILTERSPEC[n];
            for (int i = 0; i < n; i++) {
                specs[i].pszName = filterLabels[i];
                specs[i].pszSpec = filterSpecs[i];
            }
            int sz = Marshal.SizeOf(typeof(COMDLG_FILTERSPEC));
            IntPtr pSpecs = Marshal.AllocCoTaskMem(sz * n);
            for (int i = 0; i < n; i++)
                Marshal.StructureToPtr(specs[i], IntPtr.Add(pSpecs, i * sz), false);
            dlg.SetFileTypes((uint)n, pSpecs);
            Marshal.FreeCoTaskMem(pSpecs);
        }

        int hr = dlg.Show(hwnd);
        if (hr != 0) return "";

        IShellItem item;
        dlg.GetResult(out item);
        if (item == null) return "";

        string path;
        item.GetDisplayName(SIGDN_FILESYSPATH, out path);
        return path ?? "";
    }
}
"@

Add-Type -TypeDefinition $csharp -Language CSharp

$pickFolder = ($Mode -eq "folder")

# Parse filter string (pipe-delimited: "Label|*.ext|Label2|*.ext2")
$labels = @()
$specs = @()
if ($Filter -and -not $pickFolder) {
    $parts = $Filter -split '\|'
    for ($i = 0; $i -lt $parts.Length - 1; $i += 2) {
        $labels += $parts[$i]
        $specs  += $parts[$i + 1]
    }
}

$result = [FilePicker]::Pick($pickFolder, $Title, [IntPtr]::new($Hwnd), $labels, $specs)
Write-Output $result
