"""Subprocess helper that shows a Win32 IFileOpenDialog and prints the result.

Usage:
    python _win32_dialog.py folder [--title "..."] [--hwnd 12345]
    python _win32_dialog.py file   [--title "..."] [--hwnd 12345] [--filter "Label|*.ext|Label2|*.ext2"]

Prints the selected path to stdout (empty line if cancelled).
Runs on the main thread with proper STA COM initialisation — avoids all
threading / apartment issues that plague in-process approaches.
"""
import argparse
import ctypes
import ctypes.wintypes
import sys
from ctypes import HRESULT, POINTER, byref


def _show_file_dialog(pick_folder=False, title="Select", owner_hwnd=0, filter_pairs=None):
    """Show IFileOpenDialog and return selected path (or empty string)."""
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)  # STA on main thread

    F = ctypes.WINFUNCTYPE  # __stdcall

    CLSID_FileOpenDialog = ctypes.c_char_p(
        b"\x9c\x5a\x1c\xdc\x8a\xe8\xde\x4d\xa5\xa1\x60\xf8\x2a\x20\xae\xf7"
    )
    IID_IFileOpenDialog = ctypes.c_char_p(
        b"\x88\x72\x7c\xd5\xad\xd4\x68\x47\xbe\x02\x9d\x96\x95\x32\xd9\x60"
    )

    FOS_PICKFOLDERS = 0x00000020
    FOS_FORCEFILESYSTEM = 0x00000040
    SIGDN_FILESYSPATH = 0x80058000

    try:
        dialog = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            CLSID_FileOpenDialog, None, 1,  # CLSCTX_INPROC_SERVER
            IID_IFileOpenDialog, byref(dialog),
        )
        if hr != 0:
            return ""

        vtable = ctypes.cast(
            ctypes.cast(dialog, POINTER(ctypes.c_void_p))[0],
            POINTER(ctypes.c_void_p),
        )

        # GetOptions(10), SetOptions(9)
        _GetOptions = F(HRESULT, ctypes.c_void_p, POINTER(ctypes.c_uint))(vtable[10])
        _SetOptions = F(HRESULT, ctypes.c_void_p, ctypes.c_uint)(vtable[9])
        opts = ctypes.c_uint()
        _GetOptions(dialog, byref(opts))
        new_opts = opts.value | FOS_FORCEFILESYSTEM
        if pick_folder:
            new_opts |= FOS_PICKFOLDERS
        _SetOptions(dialog, new_opts)

        # SetTitle(15)
        _SetTitle = F(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p)(vtable[15])
        _SetTitle(dialog, title)

        # SetFileTypes(4) — only for file mode
        if not pick_folder and filter_pairs:
            class COMDLG_FILTERSPEC(ctypes.Structure):
                _fields_ = [("pszName", ctypes.c_wchar_p), ("pszSpec", ctypes.c_wchar_p)]

            n = len(filter_pairs)
            arr = (COMDLG_FILTERSPEC * n)()
            for i, (label, pattern) in enumerate(filter_pairs):
                arr[i].pszName = label
                arr[i].pszSpec = pattern

            _SetFileTypes = F(HRESULT, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p)(vtable[4])
            _SetFileTypes(dialog, n, ctypes.cast(arr, ctypes.c_void_p))

        # Bring ourselves to the foreground before showing
        user32 = ctypes.windll.user32
        if owner_hwnd:
            # Attach our input queue to the owner's thread so we can steal focus
            kernel32 = ctypes.windll.kernel32
            fg_tid = user32.GetWindowThreadProcessId(owner_hwnd, None)
            my_tid = kernel32.GetCurrentThreadId()
            if fg_tid and fg_tid != my_tid:
                user32.AttachThreadInput(my_tid, fg_tid, True)

        # Show(3)
        _Show = F(HRESULT, ctypes.c_void_p, ctypes.c_void_p)(vtable[3])
        hwnd_arg = ctypes.c_void_p(owner_hwnd) if owner_hwnd else None
        hr = _Show(dialog, hwnd_arg)
        print(f"[HELPER] Show hr={hr:#x}", file=sys.stderr)

        path_result = ""
        if hr == 0:
            # GetResult(18) — use c_size_t to see raw pointer value
            _GetResult = F(HRESULT, ctypes.c_void_p, POINTER(ctypes.c_size_t))(vtable[18])
            item_raw = ctypes.c_size_t(0)
            hr2 = _GetResult(dialog, byref(item_raw))
            print(f"[HELPER] GetResult hr={hr2:#x}, item_raw={item_raw.value:#x}", file=sys.stderr)
            item = ctypes.c_void_p(item_raw.value)
            if hr2 == 0 and item_raw.value:
                item_vt = ctypes.cast(
                    ctypes.cast(item, POINTER(ctypes.c_void_p))[0],
                    POINTER(ctypes.c_void_p),
                )
                # IShellItem::GetDisplayName(5)
                _GetDisplayName = F(
                    HRESULT, ctypes.c_void_p, ctypes.c_uint, POINTER(ctypes.c_wchar_p)
                )(item_vt[5])
                pstr = ctypes.c_wchar_p()
                hr3 = _GetDisplayName(item, SIGDN_FILESYSPATH, byref(pstr))
                print(f"[HELPER] GetDisplayName hr={hr3:#x}, pstr={pstr.value}", file=sys.stderr)
                if hr3 == 0:
                    path_result = pstr.value or ""
                    ole32.CoTaskMemFree(pstr)
                # Release IShellItem
                F(ctypes.c_ulong, ctypes.c_void_p)(item_vt[2])(item)
        else:
            print(f"[HELPER] Show returned non-zero, user cancelled or error", file=sys.stderr)

        # Release dialog
        F(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(dialog)
        print(f"[HELPER] Returning path_result='{path_result}'", file=sys.stderr)
        return path_result
    finally:
        ole32.CoUninitialize()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["folder", "file"])
    parser.add_argument("--title", default="Select")
    parser.add_argument("--hwnd", type=int, default=0)
    parser.add_argument("--filter", default="")
    args = parser.parse_args()

    filter_pairs = None
    if args.filter:
        parts = args.filter.split("|")
        filter_pairs = [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]

    result = _show_file_dialog(
        pick_folder=(args.mode == "folder"),
        title=args.title,
        owner_hwnd=args.hwnd,
        filter_pairs=filter_pairs,
    )
    # Print result to stdout — the parent process reads this
    print(result)


if __name__ == "__main__":
    main()
