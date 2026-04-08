// Shared nav and footer injector
document.addEventListener('DOMContentLoaded', () => {
  const page = document.body.dataset.page || '';

  const navHTML = `
  <nav>
    <a href="index.html" class="nav-name">Madiha Sattar</a>
    <ul class="nav-links">
      <li><a href="about.html" ${page==='about'?'class="active"':''}>About</a></li>
      <li><a href="fiction.html" ${page==='fiction'?'class="active"':''}>Fiction</a></li>
      <li><a href="reporting.html" ${page==='reporting'?'class="active"':''}>Reporting &amp; Analysis</a></li>
      <li><a href="interviews.html" ${page==='interviews'?'class="active"':''}>Interviews</a></li>
      <li><a href="book-reviews.html" ${page==='reviews'?'class="active"':''}>Book Reviews</a></li>
    </ul>
  </nav>`;

  const footerHTML = `
  <footer>
    <span class="copy">© Madiha Sattar</span>
    <a href="mailto:madiha.s@gmail.com">madiha.s@gmail.com</a>
    <a href="https://twitter.com/MadihaSattar" target="_blank" rel="noopener">@MadihaSattar</a>
  </footer>`;

  if (page !== 'home') {
    document.body.insertAdjacentHTML('afterbegin', navHTML);
  }
  document.body.insertAdjacentHTML('beforeend', footerHTML);
});
