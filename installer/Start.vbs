Option Explicit
Dim fso, sh, dir, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("Wscript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir

Function IsUp()
  On Error Resume Next
  Dim http
  Set http = CreateObject("MSXML2.XMLHTTP")
  http.Open "GET", "http://127.0.0.1:47631/health", False
  http.Send
  If Err.Number = 0 Then
    IsUp = (http.Status = 200)
  Else
    IsUp = False
  End If
  Err.Clear
  On Error GoTo 0
End Function

If Not IsUp() Then
  sh.Run """" & dir & "\kjor.bat""", 0, False
  For i = 1 To 40
    WScript.Sleep 500
    If IsUp() Then Exit For
  Next
End If

If IsUp() Then
  sh.Run "http://127.0.0.1:47631/"
Else
  MsgBox "Mine filmer rakk ikke a starte. Prov ikonet en gang til.", 48, "Mine filmer"
End If
