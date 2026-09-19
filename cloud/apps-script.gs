/**
 * Приймач результатів тесту для Google Таблиці (Google Apps Script).
 *
 * Куди вставляти: Google Таблиця -> Розширення -> Apps Script -> замінити
 * увесь код на цей файл -> Розгорнути -> Нове розгортання -> Веб-застосунок
 * (Виконувати як: Я; Доступ: Усі) -> скопіювати URL, що закінчується на /exec,
 * і вставити його в RESULTS_ENDPOINT у index.html.
 *
 * Що робить кожне проходження тесту:
 *  - додає рядок-огляд у перший аркуш (ім'я там є посиланням на вкладку учасника);
 *  - додає блок у вкладку учасника (назва вкладки = ім'я): дата, рівень,
 *    відсотки і список його неправильних відповідей;
 *  - якщо NOTIFY_BY_EMAIL = true, надсилає лист власнику скрипта.
 * Учасники без імені потрапляють у вкладку «Без імені».
 */

const NOTIFY_BY_EMAIL = true;
const LEVELS = ['A1', 'A2', 'B1', 'B2'];
const HEADERS = [
  'Дата і час', 'Рівень', 'Правильних', 'Всього', 'Загальний %',
  'A1 %', 'A2 %', 'B1 %', 'B2 %',
  'A1 правильних', 'A2 правильних', 'B1 правильних', 'B2 правильних',
  "Ім'я",
];
const NAME_COLUMN = HEADERS.length;

const LEGACY_MISTAKES_SHEET = 'Помилки';
const PARTICIPANT_PREFIX = 'Учасник: ';
const ANONYMOUS_TAB = 'Без імені';
const BLOCK_COLUMNS = 4;

function cleanText_(value, max) {
  if (typeof value !== 'string') throw new Error('bad text');
  return value.replace(/[\x00-\x1f\x7f]+/g, ' ').trim().slice(0, max);
}

function cleanMistakes_(items) {
  if (items === undefined || items === null) return [];
  if (!Array.isArray(items) || items.length > 100) throw new Error('bad mistakes');
  return items.map(function (m) {
    if (!m || LEVELS.indexOf(m.level) === -1) throw new Error('bad mistake');
    return {
      level: m.level,
      q: cleanText_(m.q, 300),
      chosen: cleanText_(m.chosen, 200),
      correct: cleanText_(m.correct, 200),
    };
  });
}

function cleanName_(value) {
  if (typeof value !== 'string') return '';
  return value.replace(/[\x00-\x1f\x7f\s]+/g, ' ').trim().slice(0, 60);
}

function intIn_(value, lo, hi) {
  if (typeof value !== 'number' || value % 1 !== 0 || value < lo || value > hi) {
    throw new Error('bad number');
  }
  return value;
}

// The URL is public, so accept only the exact expected shape.
function clean_(data) {
  if (!data || LEVELS.indexOf(data.level) === -1 || !data.byLevel || !data.raw) {
    throw new Error('bad payload');
  }
  const byLevel = {};
  const correct = {};
  LEVELS.forEach(function (l) {
    byLevel[l] = intIn_(data.byLevel[l], 0, 100);
    correct[l] = intIn_((data.raw[l] || {}).correct, 0, 1000);
  });
  return {
    name: cleanName_(data.name),
    mistakes: cleanMistakes_(data.mistakes),
    level: data.level,
    totalCorrect: intIn_(data.totalCorrect, 0, 1000),
    total: intIn_(data.total, 1, 1000),
    overallPct: intIn_(data.overallPct, 0, 100),
    byLevel: byLevel,
    correct: correct,
  };
}

// A participant tab is recognised by its title in A1, so tabs can be
// reordered or renamed without confusing the script.
function isParticipantTab_(sheet) {
  if (sheet.getLastRow() === 0) return false;
  return String(sheet.getRange(1, 1).getValue()).indexOf(PARTICIPANT_PREFIX) === 0;
}

function mainSheet_(ss) {
  const sheets = ss.getSheets();
  for (let i = 0; i < sheets.length; i++) {
    if (sheets[i].getName() !== LEGACY_MISTAKES_SHEET && !isParticipantTab_(sheets[i])) {
      return sheets[i];
    }
  }
  return ss.insertSheet('Результати', 0);
}

function findSheetByName_(ss, title) {
  const low = title.toLowerCase();
  const sheets = ss.getSheets();
  for (let i = 0; i < sheets.length; i++) {
    if (sheets[i].getName().toLowerCase() === low) return sheets[i];
  }
  return null;
}

// Sheet titles are case-insensitive, max 100 chars and cannot hold [ ] * ? : / \
function tabTitle_(name, mainName) {
  const title = name.replace(/[\[\]*?:\/\x5c]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 90);
  if (!title) return ANONYMOUS_TAB;
  const low = title.toLowerCase();
  const reserved = [mainName, LEGACY_MISTAKES_SHEET, ANONYMOUS_TAB];
  for (let i = 0; i < reserved.length; i++) {
    if (low === reserved[i].toLowerCase()) return title + ' (учасник)';
  }
  return title;
}

function participantTab_(ss, title, name) {
  let tab = findSheetByName_(ss, title);
  if (tab && !isParticipantTab_(tab)) {
    title = title + ' (учасник)';
    tab = findSheetByName_(ss, title);
  }
  if (!tab) {
    tab = ss.insertSheet(title, ss.getNumSheets());
    const head = tab.getRange(1, 1);
    head.setNumberFormat('@');
    head.setValue(PARTICIPANT_PREFIX + (name || ANONYMOUS_TAB));
    head.setFontWeight('bold');
    tab.setColumnWidth(1, 170);
    tab.setColumnWidth(2, 430);
    tab.setColumnWidth(3, 200);
    tab.setColumnWidth(4, 200);
  }
  return tab;
}

// One block per attempt, everything as plain text (never a formula).
function writeAttempt_(tab, d, stamp) {
  const rows = [[
    stamp,
    'Рівень ' + d.level + ' · ' + d.totalCorrect + '/' + d.total + ' (' + d.overallPct + '%)',
    LEVELS.map(function (l) { return l + ' ' + d.byLevel[l] + '%'; }).join(' · '),
    '',
  ]];
  if (d.mistakes.length) {
    rows.push(['Рівень питання', 'Питання', 'Відповідь учасника', 'Правильна відповідь']);
    d.mistakes.forEach(function (m) {
      rows.push([m.level, m.q, m.chosen, m.correct]);
    });
  } else {
    rows.push(['Помилок немає', '', '', '']);
  }
  const start = tab.getLastRow() + 2;
  const range = tab.getRange(start, 1, rows.length, BLOCK_COLUMNS);
  range.setNumberFormat('@');
  range.setValues(rows);
  tab.getRange(start, 1, 1, BLOCK_COLUMNS).setFontWeight('bold');
  if (d.mistakes.length) {
    tab.getRange(start + 1, 1, 1, BLOCK_COLUMNS).setFontWeight('bold');
  }
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    const d = clean_(JSON.parse(e.postData.contents));

    lock.waitLock(10000);
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = mainSheet_(ss);
    const now = new Date();
    const stamp = Utilities.formatDate(now, Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');
    const tab = participantTab_(ss, tabTitle_(d.name, sheet.getName()), d.name);

    if (sheet.getLastRow() === 0) {
      sheet.appendRow(HEADERS);
    } else if (sheet.getRange(1, NAME_COLUMN).getValue() === '') {
      sheet.getRange(1, NAME_COLUMN).setValue(HEADERS[NAME_COLUMN - 1]);
    }
    sheet.appendRow([
      now, d.level, d.totalCorrect, d.total, d.overallPct,
      d.byLevel.A1, d.byLevel.A2, d.byLevel.B1, d.byLevel.B2,
      d.correct.A1, d.correct.A2, d.correct.B1, d.correct.B2,
    ]);
    // The name is a link to the participant's tab; its text sits inside a
    // string literal with quotes doubled, so it can never run as a formula.
    const label = (d.name || ANONYMOUS_TAB).replace(/"/g, '""');
    sheet.getRange(sheet.getLastRow(), NAME_COLUMN)
      .setFormula('=HYPERLINK("#gid=' + tab.getSheetId() + '","' + label + '")');

    writeAttempt_(tab, d, stamp);
    lock.releaseLock();

    if (NOTIFY_BY_EMAIL) {
      // The result is already saved; a failed email must not undo that.
      try {
        MailApp.sendEmail(
          Session.getEffectiveUser().getEmail(),
          'Тест англійської: рівень ' + d.level + ' (' + d.overallPct + '%)',
          "Ім'я: " + (d.name || '—') + '\n' +
          'Рівень: ' + d.level + '\n' +
          'Правильних: ' + d.totalCorrect + ' з ' + d.total + ' (' + d.overallPct + '%)\n' +
          'Помилок: ' + d.mistakes.length + " (вкладка «" + tab.getName() + "»)\n" +
          LEVELS.map(function (l) { return l + ': ' + d.byLevel[l] + '%'; }).join('\n')
        );
      } catch (mailErr) {
        console.error('Email failed: ' + mailErr);
      }
    }
    return json_({ ok: true });
  } catch (err) {
    console.error('doPost failed: ' + err);
    return json_({ ok: false });
  }
}

function doGet() {
  return json_({ ok: true, info: 'Test results receiver is running' });
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
