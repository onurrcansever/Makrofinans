on run
  set projectDir to "__PROJECT_DIR__"
  set inner to projectDir & "/macos/launcher_inner.sh"
  try
    do shell script "export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin; /bin/bash " & quoted form of inner
  on error errMsg
    display alert "TL Yatirim Asistani" message errMsg as critical
  end try
end run
