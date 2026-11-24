// Transparently recovers from a stale CSRF token on login/signup forms.
//
// Logging in rotates the CSRF cookie. If the user had this same form open in
// another tab/browser before that happened, the hidden csrfmiddlewaretoken
// field here is stale and the POST would 403. Instead of showing that error,
// fetch a fresh token and retry once before falling back to a normal submit.
document.addEventListener("DOMContentLoaded", function () {
  var form = document.querySelector("form.auth-form");
  if (!form) return;

  var csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
  if (!csrfInput) return;

  var retried = false;

  form.addEventListener("submit", function (e) {
    if (retried) return; // second attempt submits natively
    e.preventDefault();

    var formData = new FormData(form);

    fetch(form.action, {
      method: "POST",
      body: formData,
      credentials: "same-origin",
    })
      .then(function (resp) {
        if (resp.status !== 403) return resp;

        // Stale token: pull a fresh one from the current page and retry.
        return fetch(window.location.pathname, { credentials: "same-origin" })
          .then(function (r) {
            return r.text();
          })
          .then(function (html) {
            var match = html.match(
              /name="csrfmiddlewaretoken" value="([^"]+)"/
            );
            if (match) {
              csrfInput.value = match[1];
              formData.set("csrfmiddlewaretoken", match[1]);
            }
            return fetch(form.action, {
              method: "POST",
              body: formData,
              credentials: "same-origin",
            });
          });
      })
      .then(function (resp) {
        if (resp.redirected) {
          window.location = resp.url;
          return;
        }
        // Validation errors or anything else: let Django render it normally.
        retried = true;
        form.submit();
      })
      .catch(function () {
        retried = true;
        form.submit();
      });
  });
});
