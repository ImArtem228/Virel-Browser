# Virel Browser 💜


## Low-memory mode and security-key prompts

Virel starts Qt WebEngine with Chromium's `--enable-low-end-device-mode` to reduce memory pressure on computers with limited RAM. Hardware acceleration is left enabled because software rendering can be slower on this hardware. This may reduce stutter, but it cannot guarantee perfectly smooth playback on every site.

Virel also blocks WebAuthn passkey/security-key requests in page JavaScript to prevent the Windows Security USB-key prompt shown by some Google sign-in flows. This means **passkey and hardware security-key sign-in/registration are disabled in Virel**; use another sign-in method offered by the website. It does not sign you in or bypass account verification.

Regular-window cookies/profile data, bookmarks, history and settings continue to be saved. Private windows use an in-memory profile and should not persist their cookies or history after the private window is closed.

If RTSS displays its gaming overlay on the browser, the overlay is external to Virel. To keep RTSS from hooking the generic `python.exe` process, build and run the packaged application with `build_exe.bat`, then set the `dist\VirelBrowser\VirelBrowser.exe` RTSS profile's **Application detection level** to **None**. Do this only for Virel's profile, not globally. The build has not been runtime-tested in this environment.


**Virel Browser** — браузер с фиолетовым оформлением на Python, PySide6 и Qt WebEngine. Проект рассчитан на Windows 10/11; интерфейс лёгкий, но сам движок сайтов основан на Chromium, поэтому расход памяти зависит от открытых страниц.

## Что улучшено в Performance build

- Background tabs are frozen after a short idle delay when Qt WebEngine marks them safe to suspend; tabs with active audio or pages that are still loading are left alone.
- If session restoration is enabled, only the first tab loads immediately; the other restored tabs load when selected, avoiding a burst of network and CPU activity at startup.
- History writes are debounced, and SVG interface icons are cached to avoid repeated rendering and disk writes.
- The tab strip and custom close button were made shorter to reduce the height of the tab row, while keeping a right-side inset around the close icon.
- The start page no longer uses CSS `backdrop-filter: blur()` or hover transforms. Those visual effects can trigger flickering in Qt WebEngine on Windows; the purple look is preserved with static colors and gradients.
- Smooth scroll animation is disabled for lower-end graphics, while hardware acceleration and the Chromium sandbox remain enabled.

These are resource-saving measures, not a guarantee that heavy sites or video playback will be perfectly smooth on every Celeron/4 GB system. The page content itself can still use substantial memory and CPU.

## Что уже работает

- Настоящие сайты с поддержкой HTML, CSS и JavaScript.
- Вкладки: создание, закрытие, перетаскивание, повторное открытие недавно закрытой вкладки.
- Адресная строка: URL или поисковый запрос.
- Выбор поисковика: Google, DuckDuckGo или Bing.
- Своя стартовая страница Virel с быстрыми ссылками.
- Назад, вперёд, обновление и домашняя страница.
- Закладки и история, которые сохраняются локально.
- Загрузки: выбор места сохранения, список статусов и открытие папки загрузок.
- Приватные окна (`Ctrl+Shift+N`) с отдельным временным профилем браузера.
- Поиск по странице (`Ctrl+F`), очистка истории/cookies/кэша.
- Настройка оттенка фиолетового и опциональное восстановление обычных вкладок при запуске.
- Иконка приложения, собственная страница новой вкладки и тёмная тема.

### Клавиатура

| Сочетание | Действие |
|---|---|
| `Ctrl+T` | Новая вкладка |
| `Ctrl+W` | Закрыть вкладку |
| `Ctrl+Shift+T` | Повторно открыть закрытую вкладку |
| `Ctrl+L` | Фокус на адресной строке |
| `Ctrl+R` | Обновить страницу |
| `Ctrl+D` | Добавить/удалить закладку |
| `Ctrl+H` | История |
| `Ctrl+J` | Загрузки |
| `Ctrl+F` | Найти текст на странице |
| `Ctrl+Shift+N` | Приватное окно |

## Как запустить в Windows

1. Распакуй папку `VirelBrowser` в удобное место.
2. Установи 64-битный Python 3.11 или новее с [официального сайта Python](https://www.python.org/downloads/windows/). При установке включи **Add Python to PATH**.
3. Дважды нажми `install_and_run.bat`. Скрипт установит зависимости и запустит браузер.
4. В дальнейшем запускай через `run.bat`.

Либо открой командную строку в папке проекта и выполни:

```bat
python -m pip install -r requirements.txt
python main.py
```

Установка PySide6 загружает большой пакет вместе с движком сайтов. На диске желательно иметь примерно 1–2 ГБ свободного места для зависимостей, кэша и возможной сборки — точный объём зависит от версии Python и загрузок.

## Где хранятся данные

Обычный профиль, кэш, cookies, история, закладки, настройки и список вкладок для возможного восстановления хранятся отдельно от папки проекта в пользовательской папке данных приложения (`%APPDATA%\VirelBrowser` в Windows). В приватных окнах история и закладки не записываются в JSON-файлы браузера, а профиль работает без постоянного хранилища. Файлы, которые ты скачиваешь в приватном окне, всё равно сохраняются в указанное тобой место.

## Сборка в EXE (необязательно)

После установки зависимостей запусти `build_exe.bat`. Скрипт пытается собрать папочную версию в `dist\VirelBrowser`. Из-за Qt WebEngine результат будет значительно больше исходного ZIP. Эта сборка не проверялась на целевом Windows-компьютере; если сборка не получится, используй `run.bat`.

## Важные ограничения

- Это самостоятельный проект, а не браузер с независимым аудитом безопасности. Не используй первую версию для чувствительных задач, например интернет-банкинга.
- Здесь пока **нет встроенного блокировщика рекламы/трекеров** и обещаний полной анонимности.
- На ноутбуке с 4 ГБ ОЗУ лучше не держать много тяжёлых вкладок и видео одновременно.
- Для работы с сайтами нужен интернет; первый запуск также скачивает библиотеки.

## Файлы проекта

- `main.py` — приложение и логика браузера.
- `assets/start.html` — стартовая страница Virel.
- `virel.ico`, `virel.png` — иконка приложения.
- `requirements.txt` — зависимости.
- `install_and_run.bat` — установка и запуск.
- `run.bat` — повторный запуск.
- `build_exe.bat` — необязательная попытка сборки в EXE.

## Лицензия

MIT. См. `LICENSE`.

## Visual update — Purple UI

The latest source uses custom vector (SVG) icons for Back, Forward, Reload, Home, Bookmarks, the menu, Find controls, and New Tab. The default platform tab-close square has been replaced by a small custom close button with a subtle violet hover effect. The icons render at runtime through QtSvg and do not need separate image files.
