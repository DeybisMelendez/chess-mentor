(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState !== "loading") {
      fn();
    } else {
      document.addEventListener("DOMContentLoaded", fn);
    }
  }

  ready(function () {
    var drawer = document.querySelector(".drawer");
    var toggle = document.querySelector(".drawer-toggle");
    var closeBtn = document.querySelector(".drawer__close");
    var backdrop = document.querySelector(".drawer-backdrop");

    if (!drawer || !toggle) {
      return;
    }

    function openDrawer() {
      drawer.classList.add("is-open");
      if (backdrop) backdrop.classList.add("is-open");
      document.body.classList.add("drawer-open");
      toggle.setAttribute("aria-expanded", "true");
    }

    function closeDrawer() {
      drawer.classList.remove("is-open");
      if (backdrop) backdrop.classList.remove("is-open");
      document.body.classList.remove("drawer-open");
      toggle.setAttribute("aria-expanded", "false");
    }

    toggle.addEventListener("click", function () {
      if (drawer.classList.contains("is-open")) {
        closeDrawer();
      } else {
        openDrawer();
      }
    });

    if (closeBtn) {
      closeBtn.addEventListener("click", closeDrawer);
    }

    if (backdrop) {
      backdrop.addEventListener("click", closeDrawer);
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && drawer.classList.contains("is-open")) {
        closeDrawer();
      }
    });

    // Close drawer on mobile when navigating
    var navLinks = drawer.querySelectorAll("a");
    var mq = window.matchMedia("(max-width: 768px)");
    navLinks.forEach(function (link) {
      link.addEventListener("click", function () {
        if (mq.matches) {
          closeDrawer();
        }
      });
    });
  });
})();
