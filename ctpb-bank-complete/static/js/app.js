/* CTPB Bank — front-end behaviour (vanilla JS, no build step). */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  /* ---------------- toasts ---------------- */
  const ICONS = { success: "✅", error: "⛔", info: "ℹ️", warn: "⚠️", warning: "⚠️" };
  function toast(message, type = "info") {
    const stack = $("#toasts");
    if (!stack) return;
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = `<span>${ICONS[type] || ""} ${message}</span><button aria-label="Dismiss">×</button>`;
    el.querySelector("button").addEventListener("click", () => el.remove());
    stack.appendChild(el);
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 350); }, 6000);
  }
  window.toast = toast;

  // Replay a toast stored before a redirect (e.g. after a successful transfer).
  try {
    const queued = JSON.parse(sessionStorage.getItem("ctpb.toast") || "null");
    if (queued) { sessionStorage.removeItem("ctpb.toast"); toast(queued.msg, queued.type); }
  } catch (_) { /* ignore */ }
  // Server-side flashes.
  (window.__flashes || []).forEach(([cat, msg]) => toast(msg, cat === "message" ? "info" : cat));

  /* ---------------- helpers ---------------- */
  function inr(n) {
    const neg = n < 0; n = Math.abs(n);
    const [i, f] = n.toFixed(2).split(".");
    const g = i.length > 3 ? i.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + i.slice(-3) : i;
    return `${neg ? "−" : ""}₹${g}.${f}`;
  }
  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* non-JSON (e.g. login redirect) */ }
    if (res.redirected || res.status === 401 || res.status === 403) {
      window.location.assign("/login");
      throw new Error("session expired");
    }
    return { status: res.status, data };
  }
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const initials = (name) => name.split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]).join("").toUpperCase();

  /* ---------------- modals ---------------- */
  function openModal(id) {
    const m = document.getElementById(id);
    if (!m) return;
    m.classList.add("open");
    document.body.classList.add("noscroll");
    const first = m.querySelector("input, select, button:not(.x)");
    if (first) setTimeout(() => first.focus(), 120);
  }
  function closeModal(m) { m.classList.remove("open"); document.body.classList.remove("noscroll"); }
  $$("[data-open-modal]").forEach((b) => b.addEventListener("click", () => openModal(b.dataset.openModal)));
  $$(".modal-backdrop").forEach((bd) => {
    bd.addEventListener("click", (e) => { if (e.target === bd) closeModal(bd); });
    $$("[data-close-modal]", bd).forEach((x) => x.addEventListener("click", () => closeModal(bd)));
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $$(".modal-backdrop.open").forEach(closeModal); });

  /* ---------------- copy buttons ---------------- */
  $$("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); toast(`Copied ${b.dataset.copy}`, "success"); }
    catch (_) { toast("Copy failed — select the number manually.", "error"); }
  }));

  /* ---------------- animated counters ---------------- */
  $$("[data-count]").forEach((el) => {
    const target = parseFloat(el.dataset.count);
    if (!isFinite(target)) return;
    const t0 = performance.now(), dur = 900;
    (function tick(t) {
      const p = Math.min((t - t0) / dur, 1);
      el.textContent = inr(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(tick);
    })(t0);
  });

  /* ---------------- session countdown ---------------- */
  const timer = $("#session-timer");
  if (timer) {
    let left = parseInt(timer.dataset.seconds || "1800", 10);
    const pill = timer.closest(".session-pill");
    setInterval(() => {
      left -= 1;
      if (left <= 0) { window.location.reload(); return; } // server bounces to login
      const mm = String(Math.floor(left / 60)).padStart(2, "0");
      const ss = String(left % 60).padStart(2, "0");
      timer.textContent = `${mm}:${ss}`;
      if (left < 120 && pill) pill.classList.add("warn");
    }, 1000);
    timer.textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:00`;
  }

  /* ---------------- live balance refresh ---------------- */
  const balanceEls = () => $$("[data-balance-id]");
  if (balanceEls().length) {
    setInterval(async () => {
      try {
        const res = await fetch("/api/balance");
        if (!res.ok) return;
        const payload = await res.json();
        if (!payload.ok) return;
        payload.accounts.forEach((a) => {
          const el = document.querySelector(`[data-balance-id="${a.id}"]`);
          if (el) el.textContent = inr(parseFloat(a.balance));
        });
        const totalEl = $("[data-total-balance]");
        if (totalEl) totalEl.textContent = inr(parseFloat(payload.total));
      } catch (_) { /* offline tolerance */ }
    }, 25000);
  }

  /* ---------------- shared: account validation widget ---------------- */
  function payeeCard(d) {
    if (!d.found) {
      return `<div class="bad"><span class="payee-avatar">✕</span>
        <div class="payee-meta"><strong>Account not found</strong><br>
        <small>No account with number <code>${d.number || "—"}</code>. Check and try again.</small></div></div>`;
    }
    if (d.status !== "active") {
      return `<div class="bad"><span class="payee-avatar">❄</span>
        <div class="payee-meta"><strong>${d.holder}</strong> · ${d.account_type} <code>${d.number}</code><br>
        <small>This account is frozen and cannot receive money.</small></div></div>`;
    }
    return `<div><span class="payee-avatar">${initials(d.holder)}</span>
      <div class="payee-meta"><strong>${d.holder}</strong> ✓<br>
      <small>${d.account_type} account · <code>${d.number}</code> · active</small></div></div>`;
  }

  async function validateAccount(number) {
    const { data } = await postJSON("/api/validate-account", { account_number: number });
    return data;
  }

  /* ---------------- validate-account modal ---------------- */
  const vaGo = $("#va-go");
  if (vaGo) {
    vaGo.addEventListener("click", async () => {
      const out = $("#va-result");
      out.innerHTML = "";
      const number = $("#va-number").value;
      vaGo.disabled = true; vaGo.textContent = "Checking…";
      try { out.innerHTML = payeeCard(await validateAccount(number)); }
      catch (e) { toast("Validation failed — are you still signed in?", "error"); }
      finally { vaGo.disabled = false; vaGo.textContent = "Validate"; }
    });
  }

  /* ---------------- denominations (greedy ATM) ---------------- */
  function denomChips(items) {
    if (!items.length) return "";
    return items.map((x) => `<span class="denom-chip">₹${x.note.toLocaleString("en-IN")} × <b>${x.count}</b></span>`).join("");
  }
  async function fetchDenoms(amount) {
    const res = await fetch(`/api/denominations?amount=${encodeURIComponent(amount)}`);
    if (!res.ok) return null;
    const data = await res.json();
    return data.ok ? data.items : null;
  }
  const dnGo = $("#dn-go");
  if (dnGo) {
    const run = async () => {
      const amt = $("#dn-amount").value.replace(/[^\d]/g, "");
      const items = amt ? await fetchDenoms(amt) : null;
      $("#dn-result").innerHTML = items ? denomChips(items) : "";
    };
    dnGo.addEventListener("click", run);
    $("#dn-amount").addEventListener("input", debounce(run, 350));
  }

  /* ---------------- transfer wizard ---------------- */
  const tfNumber = $("#tf-number");
  if (tfNumber) {
    const step1 = $("#tf-step1"), step2 = $("#tf-step2");
    const btnVal = $("#tf-validate"), btnNext = $("#tf-next"), btnBack = $("#tf-back"), btnSend = $("#tf-submit");
    const payeeSlot = $("#tf-payee"), warn = $("#tf-warn"), denoms = $("#tf-denoms");
    const fromSel = $("#tf-from"), amountIn = $("#tf-amount"), noteIn = $("#tf-note"), idemIn = $("#tf-idem");
    let payee = null;

    const newIdem = () => { idemIn.value = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()); };
    newIdem();

    function setStep(two) {
      step1.hidden = two; step2.hidden = !two;
      btnNext.hidden = two; btnBack.hidden = !two; btnSend.hidden = !two;
      $(".wp-2", $("#transferModal .wiz-progress")).classList.toggle("on", two);
      if (two) {
        $("#tf-payee-summary").innerHTML = payeeCard(payee);
        checkAmount();
        amountIn.focus();
      }
    }

    btnVal.addEventListener("click", async () => {
      payeeSlot.innerHTML = ""; btnNext.disabled = true; payee = null;
      if (!tfNumber.value.replace(/\D/g, "")) { toast("Enter the beneficiary account number first.", "warn"); return; }
      btnVal.disabled = true; btnVal.textContent = "Validating…";
      try {
        const d = await validateAccount(tfNumber.value);
        payee = d;
        payeeSlot.innerHTML = payeeCard(d);
        btnNext.disabled = !d.usable;
        if (d.usable) setTimeout(() => setStep(true), 350);
      } catch (e) { toast("Validation failed.", "error"); }
      finally { btnVal.disabled = false; btnVal.textContent = "Validate account"; }
    });
    tfNumber.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); btnVal.click(); } });

    function headroom() {
      const opt = fromSel.selectedOptions[0];
      return parseFloat(opt.dataset.balance) - parseFloat(opt.dataset.floor);
    }
    function checkAmount() {
      const raw = amountIn.value.replace(/,/g, "");
      const amt = parseFloat(raw);
      warn.hidden = true;
      if (!raw || !isFinite(amt)) { btnSend.disabled = true; denoms.innerHTML = ""; return; }
      if (amt <= 0) { warn.textContent = "Amount must be greater than zero."; warn.hidden = false; }
      else if (amt > headroom()) { warn.textContent = `Exceeds available headroom of ${inr(headroom())} on the selected account.`; warn.hidden = false; }
      else if (amt > 1000000) { warn.textContent = "Single transfers are capped at ₹10,00,000."; warn.hidden = false; }
      btnSend.disabled = !warn.hidden;
    }
    const liveDenoms = debounce(async () => {
      const amt = Math.floor(parseFloat(amountIn.value.replace(/,/g, "")) || 0);
      const items = amt > 0 && amt <= 10000000 ? await fetchDenoms(amt) : null;
      denoms.innerHTML = items ? denomChips(items) : "";
    }, 350);
    amountIn.addEventListener("input", () => { checkAmount(); liveDenoms(); });
    fromSel.addEventListener("change", checkAmount);

    btnNext.addEventListener("click", () => setStep(true));
    btnBack.addEventListener("click", () => setStep(false));

    btnSend.addEventListener("click", async () => {
      btnSend.disabled = true; btnSend.textContent = "Sending…";
      try {
        const { status, data } = await postJSON("/api/transfer", {
          from_account_id: parseInt(fromSel.value, 10),
          to_account_number: tfNumber.value,
          amount: amountIn.value,
          note: noteIn.value,
          idempotency_key: idemIn.value,
        });
        if (!data.ok) {
          toast(data.error || "Transfer failed.", "error");
          btnSend.disabled = false; btnSend.textContent = "Send money";
          return;
        }
        const msg = data.flagged
          ? `Sent ${inr(parseFloat(data.amount))} — flagged for review (${data.reasons.join(", ")}). Ref ${data.ref}`
          : `${inr(parseFloat(data.amount))} sent successfully. Ref ${data.ref}`;
        sessionStorage.setItem("ctpb.toast", JSON.stringify({ msg, type: data.flagged ? "warn" : "success" }));
        window.location.reload();
      } catch (e) {
        toast("Network error — check history before retrying (transfers are idempotent).", "error");
        btnSend.disabled = false; btnSend.textContent = "Send money";
      }
    });

    // Reset wizard whenever the modal is opened.
    document.querySelector('[data-open-modal="transferModal"]').addEventListener("click", () => {
      setStep(false); payeeSlot.innerHTML = ""; denoms.innerHTML = ""; warn.hidden = true;
      tfNumber.value = ""; amountIn.value = ""; noteIn.value = ""; newIdem(); btnNext.disabled = true;
    });
  }

  /* ---------------- admin confirm forms ---------------- */
  $$("form[data-confirm]").forEach((f) =>
    f.addEventListener("submit", (e) => { if (!confirm(f.dataset.confirm)) e.preventDefault(); })
  );

  /* ---------------- auto-submitting filters ---------------- */
  $$("[data-autosubmit]").forEach((el) => el.addEventListener("change", () => el.form.submit()));
})();
