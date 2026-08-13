// © 2026 Martín Viera. Todos los derechos reservados.
/*
 * Plania · comportamiento de la web pública
 * =========================================
 * El contenido de cada idioma se sirve ya renderizado desde /es/, /en/ y /pt/
 * (generado por sitio/build.py), así que acá no hay traducción en runtime:
 * no existe el parpadeo de texto sin traducir que tiene la i18n por JavaScript.
 *
 * Este archivo resuelve solo lo que necesita ser dinámico:
 *   1. El selector de idioma del VIDEO (independiente del idioma de la página:
 *      alguien puede leer en inglés y querer escuchar el audio en español).
 *   2. El alta de la demo de 7 días contra el backend de venta.
 *   3. El checkout de MercadoPago.
 *   4. El formulario de contacto.
 */
(function () {
  "use strict";

  var LANG = window.PLANIA_LANG || "es";
  var BACKEND = window.PLANIA_BACKEND || "";

  // ---------------------------------------------------------------------
  // Escape explícito para lo poco que se inserta con innerHTML.
  // ---------------------------------------------------------------------
  // Todo dato que venga del backend, de una API externa o del usuario y
  // termine dentro de un innerHTML pasa por acá — sin excepción, sin
  // "total, esto no lo escribe nadie más que nosotros". La licencia que
  // devuelve /licencias/trial es un JWT: no debería poder contener HTML,
  // pero la función no depende de esa promesa del backend para ser segura.
  // Cubre las cinco entidades peligrosas, no solo "<" (que es lo mínimo
  // para no poder cerrar el <textarea> antes de tiempo, pero deja pasar
  // "&" y las comillas, que rompen atributos si el HTML de alrededor
  // cambia el día de mañana).
  function escaparHtml(valor) {
    var mapa = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return String(valor).replace(/[&<>"']/g, function (c) { return mapa[c]; });
  }

  var TXT = {
    es: {
      sinBackend: "Escribinos a ventas@plania.uy y te enviamos la licencia de prueba en el día.",
      emailInvalido: "Ingresá un email válido.",
      enviando: "Enviando…",
      demoOk: "Listo. Tu licencia de 7 días es:",
      demoRepetida: "Ese email ya usó la prueba. Escribinos y la extendemos.",
      errorRed: "No pudimos conectar con el servidor. Probá de nuevo en un rato.",
      contOk: "Gracias, te respondemos en menos de 24 horas hábiles.",
      contFalta: "Completá al menos tu email y un mensaje.",
      videoFalta: "El audio en este idioma todavía no está publicado. Se reproduce la pista original con subtítulos en tu idioma."
    },
    en: {
      sinBackend: "Write to ventas@plania.uy and we will send you the trial licence the same day.",
      emailInvalido: "Please enter a valid email address.",
      enviando: "Sending…",
      demoOk: "Done. Your 7-day licence is:",
      demoRepetida: "That email already used the trial. Write to us and we will extend it.",
      errorRed: "We could not reach the server. Please try again shortly.",
      contOk: "Thank you, we will reply within 24 business hours.",
      contFalta: "Please fill in at least your email and a message.",
      videoFalta: "The audio in this language is not published yet. Playing the original track with subtitles in your language."
    },
    pt: {
      sinBackend: "Escreva para ventas@plania.uy e enviamos a licença de teste no mesmo dia.",
      emailInvalido: "Digite um e-mail válido.",
      enviando: "Enviando…",
      demoOk: "Pronto. Sua licença de 7 dias é:",
      demoRepetida: "Esse e-mail já usou o teste. Fale conosco e estendemos.",
      errorRed: "Não conseguimos conectar ao servidor. Tente novamente em instantes.",
      contOk: "Obrigado, respondemos em até 24 horas úteis.",
      contFalta: "Preencha ao menos o seu e-mail e uma mensagem.",
      videoFalta: "O áudio neste idioma ainda não foi publicado. Reproduzindo a faixa original com legendas no seu idioma."
    }
  };
  var t = TXT[LANG] || TXT.es;

  function $(sel) { return document.querySelector(sel); }
  function emailValido(v) { return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v || ""); }

  // -------------------------------------------------------------------------
  // 1. Idioma del video
  // -------------------------------------------------------------------------
  var video = $("#demo-video");
  var botonesVideo = document.querySelectorAll("[data-vlang]");

  // Activa la pista de subtítulos del idioma pedido y apaga el resto. Se hace
  // por código y no con el atributo `default` porque el usuario puede cambiar
  // de idioma sin recargar la página.
  function subtitulosEn(lang) {
    if (!video || !video.textTracks) return;
    for (var i = 0; i < video.textTracks.length; i++) {
      var pista = video.textTracks[i];
      pista.mode = (pista.language === lang) ? "showing" : "disabled";
    }
  }

  // Comprueba si existe el audio doblado a ese idioma antes de cambiar la
  // fuente: si el archivo no está publicado todavía, se deja la pista original
  // y se avisa, en vez de dejar al visitante con un video roto.
  function cambiarVideo(lang) {
    if (!video) return;
    var nuevo = "/assets/video/plania_demo_" + lang + ".mp4";
    var aviso = $("#demo-video-aviso");

    botonesVideo.forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-vlang") === lang);
    });

    fetch(nuevo, { method: "HEAD" }).then(function (r) {
      var tiempo = video.currentTime;
      var reproduciendo = !video.paused;
      if (r.ok) {
        video.querySelector("source").src = nuevo;
        video.load();
        video.currentTime = tiempo;
        if (reproduciendo) video.play();
        if (aviso) aviso.textContent = "";
      } else if (aviso) {
        aviso.textContent = t.videoFalta;
      }
      subtitulosEn(lang);
    }).catch(function () {
      subtitulosEn(lang);
    });
  }

  botonesVideo.forEach(function (b) {
    b.addEventListener("click", function () {
      cambiarVideo(b.getAttribute("data-vlang"));
    });
  });

  if (video) {
    // Arranca con los subtítulos en el idioma de la página.
    var iniciar = function () { subtitulosEn(LANG); };
    if (video.readyState >= 1) iniciar();
    video.addEventListener("loadedmetadata", iniciar);
    botonesVideo.forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-vlang") === LANG);
    });
  }

  // -------------------------------------------------------------------------
  // 2. Alta de la demo de 7 días
  // -------------------------------------------------------------------------
  var formDemo = $("#form-demo");
  if (formDemo) {
    formDemo.addEventListener("submit", function (e) {
      e.preventDefault();
      var msg = $("#demo-msg");
      var email = ($("#demo-email").value || "").trim();

      if (!emailValido(email)) { msg.textContent = t.emailInvalido; return; }
      if (!BACKEND) { msg.textContent = t.sinBackend; return; }

      msg.textContent = t.enviando;
      fetch(BACKEND + "/licencias/trial", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email })
      }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
      }).then(function (res) {
        if (res.ok) {
          msg.innerHTML = t.demoOk + '<br><textarea readonly rows="3" style="width:100%;margin-top:8px">' +
            escaparHtml(res.d.licencia) + "</textarea>";
        } else if (res.status === 409) {
          msg.textContent = t.demoRepetida;
        } else {
          msg.textContent = (res.d && res.d.detail) || t.errorRed;
        }
      }).catch(function () { msg.textContent = t.errorRed; });
    });
  }

  // -------------------------------------------------------------------------
  // 3. Checkout de MercadoPago
  // -------------------------------------------------------------------------
  document.querySelectorAll("[data-plan]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (!BACKEND) { window.location.href = "#contacto"; return; }
      var email = window.prompt($("#demo-email") ? $("#demo-email").placeholder : "email");
      if (!email || !emailValido(email)) return;
      fetch(BACKEND + "/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: b.getAttribute("data-plan"), email: email })
      }).then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.init_point) window.location.href = d.init_point;
          else window.alert((d && d.detail) || t.errorRed);
        }).catch(function () { window.alert(t.errorRed); });
    });
  });

  // -------------------------------------------------------------------------
  // 4. Contacto
  // -------------------------------------------------------------------------
  var formCont = $("#form-cont");
  if (formCont) {
    formCont.addEventListener("submit", function (e) {
      e.preventDefault();
      var msg = $("#cont-msg");
      var email = ($("#c-email").value || "").trim();
      var cuerpo = ($("#c-msg").value || "").trim();
      if (!emailValido(email) || !cuerpo) { msg.textContent = t.contFalta; return; }

      // Sin backend de correo propio se abre el cliente de mail del visitante:
      // es preferible a simular un envío que en realidad no ocurre.
      var asunto = encodeURIComponent("Plania · " + (($("#c-empresa").value || "").trim() || email));
      var texto = encodeURIComponent(
        ($("#c-nombre").value || "") + " (" + email + ")\n" +
        ($("#c-empresa").value || "") + "\n\n" + cuerpo);
      window.location.href = "mailto:ventas@plania.uy?subject=" + asunto + "&body=" + texto;
      msg.textContent = t.contOk;
    });
  }
})();
