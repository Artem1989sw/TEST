/**
 * Приймач результатів тесту для Google Таблиці (Google Apps Script).
 *
 * Куди вставляти: Google Таблиця -> Розширення -> Apps Script -> замінити
 * увесь код на цей файл -> Розгорнути -> Нове розгортання -> Веб-застосунок
 * (Виконувати як: Я; Доступ: Усі) -> скопіювати URL, що закінчується на /exec,
 * і вставити його в RESULTS_ENDPOINT у index.html.
 *
 * Кожне проходження тесту додає рядок у перший аркуш таблиці і (якщо
 * NOTIFY_BY_EMAIL = true) надсилає лист власнику скрипта.
 */

const NOTIFY_BY_EMAIL = true;
const LEVELS = ['A1', 'A2', 'B1', 'B2'];
const HEADERS = [
  'Дата і час', 'Рівень', 'Правильних', 'Всього', 'Загальний %',
  'A1 %', 'A2 %', 'B1 %', 'B2 %',
  'A1 правильних', 'A2 правильних', 'B1 правильних', 'B2 правильних',
];

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
    level: data.level,
    totalCorrect: intIn_(data.totalCorrect, 0, 1000),
    total: intIn_(data.total, 1, 1000),
    overallPct: intIn_(data.overallPct, 0, 100),
    byLevel: byLevel,
    correct: correct,
  };
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    const d = clean_(JSON.parse(e.postData.contents));

    lock.waitLock(10000);
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(HEADERS);
    }
    sheet.appendRow([
      new Date(), d.level, d.totalCorrect, d.total, d.overallPct,
      d.byLevel.A1, d.byLevel.A2, d.byLevel.B1, d.byLevel.B2,
      d.correct.A1, d.correct.A2, d.correct.B1, d.correct.B2,
    ]);
    lock.releaseLock();

    if (NOTIFY_BY_EMAIL) {
      // The result is already saved; a failed email must not undo that.
      try {
        MailApp.sendEmail(
          Session.getEffectiveUser().getEmail(),
          'Тест англійської: рівень ' + d.level + ' (' + d.overallPct + '%)',
          'Рівень: ' + d.level + '\n' +
          'Правильних: ' + d.totalCorrect + ' з ' + d.total + ' (' + d.overallPct + '%)\n' +
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
