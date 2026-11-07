# Установка набора Albumum для агента на Windows: утилита albumum и скиллы. Ключ не нужен.
#
#   irm https://raw.githubusercontent.com/ConsMikh/albumum-agent/main/install.ps1 | iex
#
# Параметры — только переменными окружения (форма «irm | iex» аргументов не принимает):
#   ALBUMUM_VERSION=X.Y.Z — выпуск вместо последнего;
#   ALBUMUM_FROM=ПАПКА    — папка с albumum_cli-*.whl и skills/ вместо скачивания;
#   ALBUMUM_NO_SKILLS=1   — только утилита;
#   ALBUMUM_WAIT_PID=N    — дождаться выхода процесса N (так albumum update отпускает свои файлы);
#                           в конце окно ждёт Enter, чтобы человек успел прочитать итог.
# Повторный запуск обновляет установку без дублей. Для macOS и Linux — install.sh.
# Windows PowerShell 5.1 и PowerShell 7. Файл в UTF-8 без BOM: irm не срезает BOM, и «irm | iex» принял
# бы его за команду. Для запуска файлом (-File) BOM дописывает albumum update: без него 5.1 читает файл как ANSI.
#
# Всё тело — один блок «& { … }»: PowerShell разбирает текст целиком до запуска, и оборванная
# загрузка без закрывающей скобки ничего не выполнит. Блок не оставляет в окне ни функций, ни переменных.
& {
  $ErrorActionPreference = 'Stop'
  $ProgressPreference = 'SilentlyContinue' # полоса прогресса в 5.1 замедляет скачивание в разы

  $Mirror = 'https://github.com/ConsMikh/albumum-agent'
  $Raw = 'https://raw.githubusercontent.com/ConsMikh/albumum-agent'
  $Marker = '.albumum-kit' # метка копии набора в каталоге скилла агента

  function Say([string]$Text) { Write-Host $Text }
  function Warn([string]$Text) { Write-Host "albumum: внимание: $Text" }
  function Stop-Install([string]$Text, [int]$Code = 1) {
    # Одна строка для человека и код выхода; трассировку ловит обработчик в конце блока.
    $reason = New-Object System.Exception $Text
    $reason.Data['albumum'] = $Code
    throw $reason
  }

  function Find-Tool([string]$Name) {
    $found = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $found.Path }
  }

  function Invoke-Tool {
    # Код возврата и stdout программы; stderr — на экран, с -Quiet — в никуда.
    # 'Continue': в 5.1 при 'Stop' перенаправленная строка stderr стала бы исключением.
    param([string]$Exe, [string[]]$ToolArgs, [switch]$Quiet)
    $ErrorActionPreference = 'Continue'
    if ($Quiet) { $out = & $Exe @ToolArgs 2>$null } else { $out = & $Exe @ToolArgs }
    [pscustomobject]@{ Code = $LASTEXITCODE; Out = ($out | Out-String) }
  }

  function Get-File([string]$Url, [string]$OutFile, [string]$What, [string]$Version) {
    try {
      Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $OutFile
    } catch {
      # Ответ 404 — файла выпуска нет, интернет в порядке; без ответа — нет связи.
      $response = $_.Exception.Response
      if ($response -and [int]$response.StatusCode -eq 404) {
        if (-not $Version) { Stop-Install 'в зеркале Albumum пока нет выпусков — обратитесь к администратору Albumum' }
        Stop-Install "выпуска $Version в зеркале нет — проверьте номер выпуска или обратитесь к администратору Albumum"
      }
      Stop-Install "не удалось скачать $What — проверьте интернет и запустите установку ещё раз"
    }
  }

  # --- скиллы ------------------------------------------------------------------------------------
  # Ссылки на Windows требуют прав, поэтому у агентов — копии общего каталога с меткой.
  function Test-KitCopy([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    $item.PSIsContainer -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
      (Test-Path -LiteralPath (Join-Path $Path $Marker) -PathType Leaf)
  }

  function Copy-Skill([string]$Source, [string]$AgentDir) {
    $target = Join-Path $AgentDir (Split-Path -Leaf $Source)
    if (Test-Path -LiteralPath $target) {
      if (-not (Test-KitCopy $target)) {
        Warn "$target — не копия набора, оставляю как есть"
        return
      }
      Remove-Item -LiteralPath $target -Recurse -Force
    }
    try {
      Copy-Item -LiteralPath $Source -Destination $target -Recurse
      Set-Content -LiteralPath (Join-Path $target $Marker) -Encoding UTF8 `
        -Value 'Копия скилла из набора Albumum: установщик перезаписывает этот каталог.'
    } catch {
      Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
      Warn "не удалось скопировать скилл в $target"
    }
  }

  function Remove-StaleCopy([string]$AgentDir, [string[]]$Names) {
    # Копии скиллов, которых в наборе больше нет. Чужие каталоги без метки не трогаются.
    Get-ChildItem -LiteralPath $AgentDir -Directory -Filter 'albumum*' -Force |
      Where-Object { $Names -notcontains $_.Name -and (Test-KitCopy $_.FullName) } |
      ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
  }

  function Install-Albumum {
    $version = "$env:ALBUMUM_VERSION".Trim()
    $from = "$env:ALBUMUM_FROM"
    $withSkills = $env:ALBUMUM_NO_SKILLS -ne '1'
    $userHome = $env:USERPROFILE
    if (-not $userHome) { $userHome = [Environment]::GetFolderPath('UserProfile') }
    $localData = $env:LOCALAPPDATA
    if (-not $localData) { $localData = [Environment]::GetFolderPath('LocalApplicationData') }
    $skillsHome = [IO.Path]::Combine($localData, 'albumum', 'skills')
    $sep = [IO.Path]::PathSeparator

    # albumum update запускает установку в отдельном окне и сразу выходит: пока он работает, его
    # albumum.exe и python.exe заняты, и uv не сможет их заменить.
    $waitPid = 0
    if ([int]::TryParse("$env:ALBUMUM_WAIT_PID", [ref]$waitPid) -and $waitPid -gt 0) {
      Wait-Process -Id $waitPid -Timeout 60 -ErrorAction SilentlyContinue
    }

    # Windows PowerShell 5.1 по умолчанию может не включать TLS 1.2, а GitHub без него не отвечает.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072

    # --- uv --------------------------------------------------------------------------------------
    $userPath = "$env:PATH"
    $env:PATH = [IO.Path]::Combine($userHome, '.local', 'bin') + $sep +
      [IO.Path]::Combine($userHome, '.cargo', 'bin') + $sep + $env:PATH
    $uv = Find-Tool 'uv'
    if (-not $uv) {
      Say 'Ставлю uv (менеджер Python-утилит)…'
      # Отдельным процессом: установщик uv не трогает переменные этого окна.
      $shell = (Get-Process -Id $PID).Path
      $result = Invoke-Tool $shell @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        ('[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; ' +
          'irm https://astral.sh/uv/install.ps1 | iex'))
      if ($result.Code -ne 0) { Stop-Install 'не удалось поставить uv — проверьте интернет и запустите установку ещё раз' }
      $uv = Find-Tool 'uv'
      if (-not $uv) { Stop-Install 'uv поставлен, но не найден — откройте терминал заново и запустите установку ещё раз' }
    }

    # --- набор -----------------------------------------------------------------------------------
    # Всё скачивается и распаковывается во временную папку до первых изменений: при ошибке
    # прежняя установка остаётся целой.
    $work = Join-Path ([IO.Path]::GetTempPath()) ('albumum-install.' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    [IO.Directory]::CreateDirectory($work) | Out-Null
    try {
      if ($from) {
        if (-not (Test-Path -LiteralPath $from -PathType Container)) { Stop-Install "папка набора не найдена: $from" }
        $wheels = @(Get-ChildItem -LiteralPath $from -Filter 'albumum_cli-*.whl' -File)
        if ($wheels.Count -eq 0) { Stop-Install "в папке $from нет колеса утилиты (albumum_cli-*.whl)" }
        if ($wheels.Count -gt 1) { Stop-Install "в папке $from несколько колёс утилиты — оставьте одно" }
        $wheel = $wheels[0].FullName
        $skillsSrc = Join-Path $from 'skills'
      } else {
        if (-not $version) {
          $versionFile = Join-Path $work 'VERSION'
          Get-File "$Raw/main/VERSION" $versionFile 'номер последнего выпуска Albumum' ''
          $version = (Get-Content -Raw -LiteralPath $versionFile).Trim()
        }
        if ($version.StartsWith('v')) { $version = $version.Substring(1) }
        if ($version -notmatch '^[0-9A-Za-z.-]+$') { Stop-Install "непонятный номер выпуска «$version» — укажите его как 1.2.3" 2 }
        $release = "$Mirror/releases/download/v$version"
        Say "Скачиваю набор Albumum $version…"
        # Имя колеса сохраняется: uv узнаёт по нему пакет и версию.
        $wheel = Join-Path $work "albumum_cli-$version-py3-none-any.whl"
        Get-File "$release/albumum_cli-$version-py3-none-any.whl" $wheel "утилиту Albumum $version" $version
        $skillsSrc = Join-Path $work 'skills'
        if ($withSkills) {
          $zip = Join-Path $work 'skills.zip'
          Get-File "$release/albumum-skills-$version.zip" $zip "скиллы Albumum $version" $version
          try {
            Expand-Archive -LiteralPath $zip -DestinationPath $skillsSrc -Force | Out-Null
          } catch {
            Stop-Install 'не удалось распаковать скиллы — запустите установку ещё раз'
          }
        }
      }
      if ($withSkills -and -not (Test-Path -LiteralPath $skillsSrc -PathType Container)) {
        Stop-Install 'в наборе нет скиллов (skills/)'
      }

      # --- утилита ---------------------------------------------------------------------------------
      Say 'Ставлю утилиту albumum…'
      if ((Invoke-Tool $uv @('tool', 'install', '--force', '--reinstall', '--quiet', $wheel)).Code -ne 0) {
        Stop-Install 'не удалось поставить утилиту albumum — запустите установку ещё раз'
      }
      $bin = (Invoke-Tool $uv @('tool', 'dir', '--bin')).Out.Trim()
      if (-not $bin) { Stop-Install 'uv не назвал папку утилит — запустите установку ещё раз' }
      $env:PATH = $bin + $sep + $env:PATH
      $albumum = Find-Tool 'albumum'
      if (-not $albumum) {
        Stop-Install "утилита поставлена, но не найдена в $bin — откройте терминал заново и запустите установку ещё раз"
      }

      if ($withSkills) {
        Say "Кладу скиллы в $skillsHome…"
        if (Test-Path -LiteralPath $skillsHome) { Remove-Item -LiteralPath $skillsHome -Recurse -Force }
        [IO.Directory]::CreateDirectory($skillsHome) | Out-Null
        Get-ChildItem -LiteralPath $skillsSrc -Force | Copy-Item -Destination $skillsHome -Recurse -Force
        $names = @(Get-ChildItem -LiteralPath $skillsHome -Directory | ForEach-Object { $_.Name })
        # OpenCode читает оба этих каталога сам.
        $agentDirs = @([IO.Path]::Combine($userHome, '.claude', 'skills'), [IO.Path]::Combine($userHome, '.agents', 'skills'))
        foreach ($dir in $agentDirs) {
          try {
            [IO.Directory]::CreateDirectory($dir) | Out-Null
          } catch {
            Warn "не удалось создать $dir — скиллы для этого агента не подключены"
            continue
          }
          foreach ($name in $names) { Copy-Skill (Join-Path $skillsHome $name) $dir }
          Remove-StaleCopy $dir $names
        }
      }
    } finally {
      Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }

    # --- итог --------------------------------------------------------------------------------------
    Say ''
    Say "Установлено: $((Invoke-Tool $albumum @('--version')).Out.Trim())."
    if ($withSkills) {
      Say 'Скиллы для Claude Code, Codex и OpenCode: %USERPROFILE%\.claude\skills и %USERPROFILE%\.agents\skills.'
    }
    $known = @($userPath.Split($sep) | ForEach-Object { $_.TrimEnd('\', '/') })
    if ($known -notcontains $bin.TrimEnd('\', '/')) {
      if ((Invoke-Tool $uv @('tool', 'update-shell') -Quiet).Code -ne 0) { Warn "не удалось добавить $bin в PATH" }
      Say 'В этом окне albumum уже работает; агента и другие открытые окна терминала откройте заново.'
    }
    # Адрес и ключ задаёт человек (albumum init); без ключа проверять нечего.
    $check = Invoke-Tool $albumum @('whoami') -Quiet
    if ($check.Code -eq 0) {
      if ((Invoke-Tool $albumum @('version') -Quiet).Code -eq 5) {
        Say 'Albumum подключён, но набор нужно обновить: albumum update'
      } else {
        Say 'Готово: Albumum подключён. Обновление после нового выпуска: albumum update'
      }
    } elseif ($check.Code -eq 1 -and $check.Out -notmatch '"no_url"') {
      Say 'Нет связи с системой — проверьте адрес и сеть, затем: albumum whoami'
    } else {
      Say 'Что дальше:'
      Say '  1. Выпустите ключ агента в редакторе Albumum (раздел «Агент»).'
      Say '  2. Подключите его: albumum init — спросит адрес системы и ключ (ввод скрыт).'
      Say '  3. Проверьте: albumum whoami'
      Say '  Или скажите своему агенту: «подключи меня к Albumum».'
    }
  }

  # Кириллица в консоли 5.1 (cp866/cp1251) и в выводе, перенаправленном в albumum update.
  # Окно остаётся в UTF-8 и после установки: так ответы albumum в нём читаются.
  try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { $null = $_ } # без консоли — не нужно

  $code = 0
  try {
    Install-Albumum
  } catch {
    $reason = $_.Exception
    if ($reason.Data.Contains('albumum')) {
      $code = $reason.Data['albumum']
      Write-Host "albumum: $($reason.Message)"
    } else {
      $code = 1
      Write-Host "albumum: установка прервалась ($($reason.Message)) — запустите установку ещё раз"
    }
  }
  # Файлом (-File, так запускает albumum update) — код выхода процесса. Через «irm | iex» exit
  # закрыл бы окно человека или агента: код остаётся в $LASTEXITCODE.
  if ($PSCommandPath) {
    if ($env:ALBUMUM_WAIT_PID) {
      # Отдельное окно albumum update закрылось бы сразу, и итог никто бы не увидел.
      Write-Host ''
      Write-Host 'Нажмите Enter, чтобы закрыть окно'
      try { $null = Read-Host } catch { $null = $_ } # без ввода (нет консоли) — просто выходим
    }
    exit $code
  }
  $global:LASTEXITCODE = $code
}
