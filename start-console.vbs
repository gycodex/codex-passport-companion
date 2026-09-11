Option Explicit
Dim shell, files, root, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & root & "\tools\start_console.ps1" & Chr(34)
result = shell.Run(command, 0, True)
If result <> 0 Then
    MsgBox "Passport could not start. Run start-console.cmd to see the error details.", 16, "Passport Companion"
End If
