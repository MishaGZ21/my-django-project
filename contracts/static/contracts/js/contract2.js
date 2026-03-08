// === Печать / сохранение договора в "чистом" виде ===
document.addEventListener('DOMContentLoaded', function () {
  const btn = document.getElementById('btn-contract-print');
  if (!btn) return;

  btn.addEventListener('click', function (e) {
    e.preventDefault();

    const wrapper = document.querySelector('.contract-wrapper');
    if (!wrapper) {
      // На всякий случай — fallback
      window.print();
      return;
    }

    // Путь к нашим стилям договора
    const cssLink = document.querySelector('link[href*="contracts/css/contract.css"]');
    const cssHref = cssLink ? cssLink.href : '';

    const printWin = window.open('', '_blank');
    if (!printWin) {
      alert('Разрешите всплывающие окна в браузере, чтобы печатать договор.');
      return;
    }

    // Собираем "чистую" HTML-страницу только с договором
    const docTitle = document.title || 'Договор';

    printWin.document.open();
    printWin.document.write(`
      <!DOCTYPE html>
      <html lang="ru">
        <head>
          <meta charset="utf-8">
          <title>${docTitle}</title>
          ${cssHref ? `<link rel="stylesheet" href="${cssHref}">` : ''}
          <style>
            /* Чуть подсоберём поля для A4 */
            @page {
              size: A4;
              margin: 10mm 12mm;
            }
            body {
              background: #ffffff;
            }
          </style>
        </head>
        <body class="contract-pdf compact">
          <div class="contract-wrapper">
            ${wrapper.innerHTML}
          </div>
        </body>
      </html>
    `);
    printWin.document.close();
    printWin.focus();
    // Дальше пользователь сам жмёт "Печать" и может выбрать "Сохранить как PDF"
  });
});
