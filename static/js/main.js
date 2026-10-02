// South Africa Time and Date
function updateSATime() {
    const now = new Date();
    const timeEl = document.getElementById('sa-time');
    const dateEl = document.getElementById('sa-date');
    if (!timeEl || !dateEl) return;

    timeEl.textContent = now.toLocaleTimeString('en-ZA', {
        timeZone: 'Africa/Johannesburg',
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    dateEl.textContent = now.toLocaleDateString('en-ZA', {
        timeZone: 'Africa/Johannesburg',
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}

updateSATime();
setInterval(updateSATime, 1000);

// Product image sliders
function initSlider(slider) {
    const track = slider.querySelector('.slider-container');
    const slides = track.children;
    const total = slides.length;
    if (total < 2) return;

    const prevBtn = slider.querySelector('.prev-slide');
    const nextBtn = slider.querySelector('.next-slide');
    const counter = slider.querySelector('.current-slide');
    const dots = slider.querySelectorAll('.slider-dot');
    let current = 0;

    function goTo(index) {
        current = (index + total) % total;
        track.style.transform = `translateX(-${current * 100}%)`;
        if (counter) counter.textContent = current + 1;
        dots.forEach((dot, i) => dot.classList.toggle('active', i === current));

        // Make sure the visible image (and the next one) start loading now
        [current, (current + 1) % total].forEach(i => {
            const img = slides[i].querySelector('img');
            if (img) img.loading = 'eager';
        });
    }

    prevBtn.addEventListener('click', () => goTo(current - 1));
    nextBtn.addEventListener('click', () => goTo(current + 1));
    dots.forEach(dot => dot.addEventListener('click', () => goTo(Number(dot.dataset.index))));

    // Swipe support on touch screens
    let startX = null;
    slider.addEventListener('touchstart', e => { startX = e.touches[0].clientX; }, { passive: true });
    slider.addEventListener('touchend', e => {
        if (startX === null) return;
        const dx = e.changedTouches[0].clientX - startX;
        if (Math.abs(dx) > 40) goTo(current + (dx < 0 ? 1 : -1));
        startX = null;
    });
}

document.querySelectorAll('[data-slider]').forEach(initSlider);

// Show a placeholder if an image fails to load
const PLACEHOLDER = 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="225" viewBox="0 0 300 225">' +
    '<rect width="300" height="225" fill="#eef2f6"/>' +
    '<text x="150" y="118" font-family="Segoe UI, sans-serif" font-size="14" fill="#6c757d" text-anchor="middle">Image not available</text>' +
    '</svg>'
);
document.querySelectorAll('.slide img').forEach(img => {
    img.addEventListener('error', () => {
        if (img.src !== PLACEHOLDER) img.src = PLACEHOLDER;
    }, { once: true });
});

// Category filter
const filterButtons = document.querySelectorAll('.filter-btn');
filterButtons.forEach(button => {
    button.addEventListener('click', () => {
        filterButtons.forEach(btn => btn.classList.remove('active'));
        button.classList.add('active');

        const filter = button.dataset.filter;
        let visible = 0;
        document.querySelectorAll('.product-card').forEach(card => {
            const show = filter === 'all' || card.dataset.category === filter;
            card.hidden = !show;
            if (show) visible++;
        });
        const noResults = document.getElementById('no-filter-results');
        const hasProducts = document.querySelectorAll('.product-card').length > 0;
        if (noResults) noResults.hidden = !hasProducts || visible > 0;
    });
});

// Smooth scrolling for same-page navigation links
document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', function (e) {
        const url = new URL(this.href);
        if (url.pathname !== window.location.pathname) return;
        const target = document.querySelector(url.hash);
        if (!target) return;
        e.preventDefault();
        window.scrollTo({ top: target.offsetTop - 100, behavior: 'smooth' });
    });
});

// Preview selected images on the admin product form
const imageInput = document.getElementById('images');
const preview = document.getElementById('upload-preview');
if (imageInput && preview) {
    imageInput.addEventListener('change', () => {
        preview.innerHTML = '';
        Array.from(imageInput.files).forEach(file => {
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.alt = file.name;
            preview.appendChild(img);
        });
    });
}
