// Shared header and footer injector (every page, including the homepage)
document.addEventListener('DOMContentLoaded', () => {
  const page = document.body.dataset.page || '';

  const link = (href, label, key) =>
    `<a href="${href}"${page === key ? ' class="active" aria-current="page"' : ''}>${label}</a>`;

  const headerHTML = `
  <header class="site-header">
    <a href="index.html" class="site-name">Madiha Sattar</a>
    <nav class="site-nav" aria-label="Main">
      ${link('index.html#about', 'About', 'about')}
      ${link('fiction.html', 'Fiction', 'fiction')}
      ${link('reporting.html', 'Reporting &amp; Analysis', 'reporting')}
      ${link('interviews.html', 'Interviews', 'interviews')}
      ${link('book-reviews.html', 'Book Reviews', 'reviews')}
    </nav>
  </header>`;

  const footerHTML = `
  <footer class="site-footer">
    <a href="mailto:madiha.s@gmail.com">madiha.s@gmail.com</a>
    <div class="site-footer-social">
      <a href="https://twitter.com/MadihaSattar" target="_blank" rel="noopener">@MadihaSattar</a>
      <a href="https://www.linkedin.com/in/madiha-sattar/" target="_blank" rel="noopener">LinkedIn</a>
    </div>
  </footer>`;

  document.body.insertAdjacentHTML('afterbegin', headerHTML);
  document.body.insertAdjacentHTML('beforeend', footerHTML);
});
