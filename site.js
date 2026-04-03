// Shared nav and footer injector
document.addEventListener('DOMContentLoaded', () => {
  const page = document.body.dataset.page || '';

  const navHTML = `
  <nav>
    <a href="index.html" class="nav-name">Madiha Sattar</a>
    <ul class="nav-links">
      <li><a href="index.html" ${page==='home'?'class="active"':''}>Home</a></li>
      <li><a href="about.html" ${page==='about'?'class="active"':''}>About</a></li>
      <li><a href="fiction.html" ${page==='fiction'?'class="active"':''}>Fiction</a></li>
      <li class="nav-dropdown">
        <span>Selected Nonfiction ▾</span>
        <div class="dropdown-menu">
          <a href="reporting.html" ${page==='reporting'?'class="active"':''}>Reporting, Analysis & Commentary</a>
          <a href="book-reviews.html" ${page==='reviews'?'class="active"':''}>Book Reviews</a>
          <a href="interviews.html" ${page==='interviews'?'class="active"':''}>Interviews</a>
        </div>
      </li>
    </ul>
    <a href="https://twitter.com/MadihaSattar" class="nav-twitter" target="_blank" rel="noopener" aria-label="Twitter">
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.73-8.835L1.254 2.25H8.08l4.253 5.622 5.911-5.622Zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
      </svg>
    </a>
    <button class="hamburger" aria-label="Menu" onclick="document.querySelector('.mobile-menu').classList.toggle('open')">
      <span></span><span></span><span></span>
    </button>
  </nav>
  <div class="mobile-menu">
    <a href="index.html">Home</a>
    <a href="about.html">About</a>
    <a href="fiction.html">Fiction</a>
    <a href="reporting.html" class="sub">— Reporting & Commentary</a>
    <a href="book-reviews.html" class="sub">— Book Reviews</a>
    <a href="interviews.html" class="sub">— Interviews</a>
    <a href="https://twitter.com/MadihaSattar" target="_blank" rel="noopener">Twitter ↗</a>
  </div>`;

  const footerHTML = `
  <footer>
    <span class="copy">© Madiha Sattar</span>
    <a href="mailto:madiha.s@gmail.com">madiha.s@gmail.com</a>
    <a href="https://twitter.com/MadihaSattar" target="_blank" rel="noopener">@MadihaSattar</a>
  </footer>`;

  document.body.insertAdjacentHTML('afterbegin', navHTML);
  document.body.insertAdjacentHTML('beforeend', footerHTML);
});
