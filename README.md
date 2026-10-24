# telegram-support-bot

🇷🇺 [Русский](#русский) · 🇬🇧 [English](#english)

---

## Русский

Бот поддержки для Telegram на aiogram 3: каждый тикет — отдельная **тема форум-группы** операторов. Опционально показывает карточку клиента из базы [SOLObot](https://github.com/Vladless/Solo_bot) (только чтение). Без SOLObot работает как обычный саппорт-бот.

### Возможности

- Клиент пишет боту в личку → создаётся тикет `#T000051` и тема в форуме. Первое (закреплённое) сообщение — карточка клиента: подписки, трафик, баланс, оплаты, email, баны. Кнопки: Закрыть / Взять / Обновить.
- Ответ оператора в теме уходит клиенту через `copy_message` (текст, фото, файлы, голос; reply сохраняется). Нет Markdown — `_` в ссылках и почте ничего не ломает.
- Статус в названии темы: 🔴 ждёт ответа · 🟡 ждём клиента · ✅ закрыт.
- Автозакрытие, если клиент молчит `AUTO_CLOSE_HOURS`; такой тикет переоткрывается, если клиент написал в течение `REOPEN_HOURS`. После ручного закрытия новое сообщение создаёт новый тикет.
- Если тему удалили — бот сразу создаёт новую с последними сообщениями.
- Оценка 1–5 ⭐ после закрытия, антиспам, баны клиентов.
- Бот не открывает портов; Docker-контейнер без root, файловая система read-only.

### Установка

Нужны Docker с Compose и сервер с доступом к api.telegram.org.

1. **Бот.** Создайте бота в [@BotFather](https://t.me/BotFather), сохраните токен. Один токен нельзя опрашивать из двух процессов (будет ошибка 409).
2. **Форум-группа.** Создайте супергруппу, включите **Topics** (Темы), добавьте бота администратором с правами «Управление темами», «Удаление сообщений», «Закрепление сообщений». Узнайте ID группы (вида `-100…`), например через [@RawDataBot](https://t.me/RawDataBot).
3. **Код и настройки:**
   ```bash
   git clone https://github.com/ShmelSiniy/telegram-support-bot.git /opt/supportbot
   cd /opt/supportbot
   cp .env.example .env
   chmod 600 .env
   nano .env            # BOT_TOKEN, FORUM_CHAT_ID, при необходимости SOLO_DSN
   mkdir -p data && chown 10001 data
   ```
4. **(Опционально) Карточка из SOLObot.** Создайте read-only роль в Postgres SOLObot и укажите её в `SOLO_DSN`. В `SOLO_DSN` подставьте то же имя базы (`…/имя_базы_solobot`). Если `SOLO_DSN` пустой, карточка будет только с данными Telegram.
   ```bash
   SOLO_DB=имя_базы_solobot   # имя базы данных SOLObot
   sudo -u postgres psql -d "$SOLO_DB" -v SOLO_DB="$SOLO_DB" <<'SQL'
   CREATE ROLE support_ro LOGIN PASSWORD 'CHANGE_ME';
   GRANT CONNECT ON DATABASE :"SOLO_DB" TO support_ro;
   GRANT USAGE ON SCHEMA public TO support_ro;
   GRANT SELECT ON users, identities, keys, tariffs, payments,
                   key_traffic_history, manual_bans, blocked_users TO support_ro;
   SQL
   ```
   Если SOLObot на том же сервере — очистите `SUPPORT_BOT_TOKEN` в его конфиге, чтобы токен не опрашивался дважды.
5. **Запуск:**
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```
6. Напишите боту с тестового аккаунта — в группе должна появиться тема с карточкой.

Обновление: `git pull && docker compose up -d --build`. База тикетов лежит в `data/support.db` — делайте резервные копии.

### Команды операторов

В теме тикета: любое сообщение — ответ клиенту · `!текст` или `/note текст` — внутренняя заметка · `/close`, `/reopen`, `/take`, `/card` (карточка новым сообщением внизу), `/ban [причина]`, `/unban`.
В общей теме: `/open` — активные тикеты · `/stats` — статистика · `/help`.

### Настройки (`.env`)

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | токен бота |
| `FORUM_CHAT_ID` | ID форум-группы операторов |
| `SOLO_DSN` | read-only DSN Postgres SOLObot (пусто — без карточки из SOLObot) |
| `TICKET_START` | с какого номера начинать нумерацию |
| `AUTO_CLOSE_HOURS` | автозакрытие при молчании клиента, 0 — выключено |
| `REOPEN_HOURS` | окно переоткрытия автозакрытого тикета |
| `SPAM_LIMIT` / `SPAM_WINDOW` | антиспам: сообщений за N секунд |
| `ASK_RATING` | запрашивать оценку после закрытия |
| `DB_PATH` | путь к SQLite |

### Безопасность

`.env` и `data/` в `.gitignore` — никогда не коммитьте токен и DSN. Роль `support_ro` должна иметь только `SELECT` на перечисленные таблицы. Весь SQL параметризован, вывод экранируется (`html.escape`).

### Разработка

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest
.venv/Scripts/python -m pytest -q
```

---

## English

A Telegram support bot built on aiogram 3: every ticket is its own **topic in an operators' forum group**. It can optionally show a client card from the [SOLObot](https://github.com/Vladless/Solo_bot) database (read-only). Without SOLObot it works as a plain support bot.

### Features

- A client messages the bot in private → ticket `#T000051` and a forum topic are created. The first (pinned) message is the client card: subscriptions, traffic, balance, payments, email, bans. Buttons: Close / Take / Refresh.
- Operator messages in the topic are delivered to the client via `copy_message` (text, photos, files, voice; replies are preserved). No Markdown, so `_` in links or emails cannot break delivery.
- Status in the topic title: 🔴 awaiting reply · 🟡 awaiting client · ✅ closed.
- Auto-close when the client is silent for `AUTO_CLOSE_HOURS`; such a ticket is reopened if the client writes within `REOPEN_HOURS`. After a manual close, a new message opens a new ticket.
- If a topic is deleted, the bot immediately recreates it with the latest messages.
- 1–5 ⭐ rating after closing, anti-flood, client bans.
- No open ports; the Docker container runs as non-root with a read-only filesystem.

### Installation

Requires Docker with Compose and a host that can reach api.telegram.org.

1. **Bot.** Create a bot with [@BotFather](https://t.me/BotFather) and save the token. A token must not be polled by two processes (409 conflict).
2. **Forum group.** Create a supergroup, enable **Topics**, add the bot as admin with the "Manage topics", "Delete messages" and "Pin messages" rights. Get the group ID (`-100…`), e.g. via [@RawDataBot](https://t.me/RawDataBot).
3. **Code and config:**
   ```bash
   git clone https://github.com/ShmelSiniy/telegram-support-bot.git /opt/supportbot
   cd /opt/supportbot
   cp .env.example .env
   chmod 600 .env
   nano .env            # BOT_TOKEN, FORUM_CHAT_ID, optionally SOLO_DSN
   mkdir -p data && chown 10001 data
   ```
4. **(Optional) SOLObot client card.** Create a read-only role in the SOLObot Postgres and put it in `SOLO_DSN`. If `SOLO_DSN` is empty, the card contains Telegram data only.
   ```bash
   SOLO_DB=your_solobot_db_name   # name of the SOLObot database
   sudo -u postgres psql -d "$SOLO_DB" -v SOLO_DB="$SOLO_DB" <<'SQL'
   CREATE ROLE support_ro LOGIN PASSWORD 'CHANGE_ME';
   GRANT CONNECT ON DATABASE :"SOLO_DB" TO support_ro;
   GRANT USAGE ON SCHEMA public TO support_ro;
   GRANT SELECT ON users, identities, keys, tariffs, payments,
                   key_traffic_history, manual_bans, blocked_users TO support_ro;
   SQL
   ```
   If SOLObot runs on the same host, clear its `SUPPORT_BOT_TOKEN` so the token is not polled twice.
5. **Run:**
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```
6. Message the bot from a test account — a topic with the card should appear in the group.

Update: `git pull && docker compose up -d --build`. Tickets live in `data/support.db` — back it up.

### Operator commands

Inside a ticket topic: any message — reply to the client · `!text` or `/note text` — internal note · `/close`, `/reopen`, `/take`, `/card` (resends the card as a new message at the bottom), `/ban [reason]`, `/unban`.
In the General topic: `/open` — active tickets · `/stats` — statistics · `/help`.

### Settings (`.env`)

| Variable | Meaning |
|---|---|
| `BOT_TOKEN` | bot token |
| `FORUM_CHAT_ID` | operators' forum group ID |
| `SOLO_DSN` | read-only SOLObot Postgres DSN (empty — no SOLObot card) |
| `TICKET_START` | number to continue ticket numbering from |
| `AUTO_CLOSE_HOURS` | auto-close after client silence, 0 — off |
| `REOPEN_HOURS` | window for reopening an auto-closed ticket |
| `SPAM_LIMIT` / `SPAM_WINDOW` | anti-flood: messages per N seconds |
| `ASK_RATING` | ask for a rating after closing |
| `DB_PATH` | SQLite path |

### Security

`.env` and `data/` are git-ignored — never commit the token or the DSN. The `support_ro` role must only have `SELECT` on the listed tables. All SQL is parameterized and output is escaped (`html.escape`).

### Development

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest
.venv/Scripts/python -m pytest -q
```

## License

MIT
