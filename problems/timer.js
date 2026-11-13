/* Countdown timer for pen-and-paper exercise Question pages.
 *
 * Markup:
 *   <div class="timer" data-minutes="20">
 *     <output></output>
 *     <button type="button" data-go>Start</button>
 *     <button type="button" data-reset>Reset</button>
 *   </div>
 *   <script src="../timer.js"></script>
 *
 * `data-minutes` must match the problem's `time_limit_minutes`; the tests
 * check that. No network and no storage: the page works straight off disk.
 */
(function () {
  document.querySelectorAll(".timer[data-minutes]").forEach(function (box) {
    var total = Math.max(1, parseInt(box.getAttribute("data-minutes"), 10) || 20) * 60;
    var left = total, tick = null;
    var clock = box.querySelector("output");
    var go = box.querySelector("[data-go]");
    var reset = box.querySelector("[data-reset]");

    function show() {
      var m = Math.floor(left / 60), s = left % 60;
      clock.textContent = (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
    }
    function stop() {
      clearInterval(tick);
      tick = null;
      go.textContent = "Start";
    }

    go.onclick = function () {
      if (tick) { stop(); return; }
      if (left === 0) { left = total; box.classList.remove("done"); }
      go.textContent = "Pause";
      tick = setInterval(function () {
        left--;
        show();
        if (left <= 0) {
          left = 0;
          show();
          stop();
          box.classList.add("done");
        }
      }, 1000);
    };
    reset.onclick = function () {
      stop();
      left = total;
      box.classList.remove("done");
      show();
    };
    show();
  });
})();
