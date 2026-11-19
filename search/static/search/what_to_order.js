// Detail page: fill the Menu box after the page has loaded, so reading
// the menu (a few seconds) never delays the rest of the page.
(function () {
  var box = document.getElementById("what-to-order");
  if (!box || !box.dataset.url) return;
  fetch(box.dataset.url, { headers: { "X-Requested-With": "fetch" } })
    .then(function (response) {
      if (!response.ok) throw new Error(response.status);
      return response.text();
    })
    .then(function (html) {
      box.innerHTML = html;
    })
    .catch(function () {
      box.innerHTML = '<p class="muted what-to-order__empty">Menu not available right now.</p>';
    })
    .finally(function () {
      box.setAttribute("aria-busy", "false");
    });
})();
