// Like / Not interested on the home page, saved in the background so the page
// does not reload (a reload redraws every card and calls Google again). The
// choice is stored now and used the next time Top picks are worked out.
//
// - Explore more heart: flips at once, flips back if saving fails.
// - Top picks Like: same.
// - Top picks Not interested: the photo turns grey and the button becomes Undo.
//
// Without JavaScript the forms still post and reload the page as before.
(function () {
  "use strict";

  function save(form, value) {
    var body = new FormData(form);
    body.set("value", value);
    return fetch(form.action, {
      method: "POST",
      body: body,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    }).then(function (response) {
      var type = response.headers.get("Content-Type") || "";
      if (!response.ok || type.indexOf("application/json") === -1) {
        throw new Error("not saved");
      }
      return response.json();
    });
  }

  function fallback(form, value) {
    // e.g. the login expired: post the normal way so the server can answer.
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = "value";
    input.value = value;
    form.appendChild(input);
    form.submit();
  }

  // ---- Explore more heart -------------------------------------------------
  function showHeart(button, liked) {
    button.classList.toggle("is-active", liked);
    button.setAttribute("aria-pressed", liked ? "true" : "false");
    button.setAttribute("aria-label", liked ? "Liked" : "Like");
    button.title = liked
      ? "Liked. Press again to undo"
      : "More like this in your Top picks";
  }

  function onHeart(form) {
    var button = form.querySelector("button");
    var wasLiked = button.classList.contains("is-active");
    form.dataset.busy = "1";
    showHeart(button, !wasLiked);
    save(form, "like")
      .then(function (data) {
        showHeart(button, Boolean(data.liked));
      })
      .catch(function () {
        showHeart(button, wasLiked);
        fallback(form, "like");
      })
      .finally(function () {
        form.dataset.busy = "";
      });
  }

  // ---- Top picks Like / Not interested ------------------------------------
  function showLike(form, liked) {
    var button = form.querySelector('button[value="like"]');
    if (!button) {
      return;
    }
    button.classList.toggle("is-active", liked);
    button.setAttribute("aria-pressed", liked ? "true" : "false");
  }

  function setHidden(form, hidden) {
    var card = form.closest(".top-pick-card");
    var like = form.querySelector('button[value="like"]');
    var skip = form.querySelector('button[value="not_interested"]');
    card.classList.toggle("is-hidden-pick", hidden);
    if (like) {
      like.disabled = hidden;
    }
    if (skip) {
      if (!skip.dataset.label) {
        skip.dataset.label = skip.innerHTML;
        skip.dataset.title = skip.title;
      }
      skip.innerHTML = hidden ? "&#8617; Undo" : skip.dataset.label;
      skip.title = hidden
        ? "Show this place again"
        : skip.dataset.title;
      skip.setAttribute("aria-pressed", hidden ? "true" : "false");
    }
  }

  function onPick(form, value) {
    var card = form.closest(".top-pick-card");
    var likeButton = form.querySelector('button[value="like"]');
    form.dataset.busy = "1";
    var done = function () {
      form.dataset.busy = "";
    };

    if (card.classList.contains("is-hidden-pick")) {
      // Undo: remove the Not interested (or bring back an earlier Like).
      var restoreLike = form.dataset.wasLiked === "1";
      save(form, restoreLike ? "like" : "not_interested")
        .then(function (data) {
          setHidden(form, false);
          showLike(form, Boolean(data.liked));
        })
        .catch(function () {
          fallback(form, restoreLike ? "like" : "not_interested");
        })
        .finally(done);
      return;
    }

    var wasLiked = Boolean(likeButton && likeButton.classList.contains("is-active"));
    if (value === "like") {
      showLike(form, !wasLiked);
      save(form, "like")
        .then(function (data) {
          showLike(form, Boolean(data.liked));
        })
        .catch(function () {
          showLike(form, wasLiked);
          fallback(form, "like");
        })
        .finally(done);
      return;
    }

    // Not interested: grey out now; the same button becomes Undo.
    form.dataset.wasLiked = wasLiked ? "1" : "";
    showLike(form, false);
    setHidden(form, true);
    save(form, "not_interested")
      .catch(function () {
        setHidden(form, false);
        showLike(form, wasLiked);
        fallback(form, "not_interested");
      })
      .finally(done);
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.classList) {
      return;
    }
    var heart = form.classList.contains("restaurant-card__like");
    var pick = form.classList.contains("top-pick-card__feedback");
    if (!heart && !pick) {
      return;
    }
    event.preventDefault();
    if (form.dataset.busy === "1") {
      return; // ignore double clicks while saving
    }
    if (heart) {
      onHeart(form);
    } else {
      var submitter = event.submitter;
      onPick(form, submitter ? submitter.value : "like");
    }
  });
})();
