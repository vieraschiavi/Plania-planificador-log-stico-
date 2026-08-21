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
 *   2. El pedido de demo (registra al interesado; no entrega licencia).
 *   3. El checkout de MercadoPago.
 *   4. El formulario de contacto.
 */
(function () {
  "use strict";

  var LANG = window.PLANIA_LANG || "es";
  var BACKEND = window.PLANIA_BACKEND || "";

  var TXT = {
    es: {
      sinBackend: "Escribinos a vieraschiavi@gmail.com y coordinamos la demo.",
      emailInvalido: "Ingresá un email válido.",
      enviando: "Enviando…",
      demoPedida: "Recibimos tu pedido. Te escribimos para coordinar la demo.",
      demoFalta: "Completá nombre, empresa y país: la demo es personal y necesitamos saber con quién hablamos.",
      errorRed: "No pudimos conectar con el servidor. Probá de nuevo en un rato.",
      contOk: "Gracias, te respondemos en menos de 24 horas hábiles.",
      contFalta: "Completá al menos tu email y un mensaje.",
      videoFalta: "El audio en este idioma todavía no está publicado. Se reproduce la pista original con subtítulos en tu idioma."
    },
    en: {
      sinBackend: "Write to vieraschiavi@gmail.com and we will arrange the demo.",
      emailInvalido: "Please enter a valid email address.",
      enviando: "Sending…",
      demoPedida: "We received your request. We will write to arrange the demo.",
      demoFalta: "Please add name, company and country: the demo is one-to-one and we need to know who we are talking to.",
      errorRed: "We could not reach the server. Please try again shortly.",
      contOk: "Thank you, we will reply within 24 business hours.",
      contFalta: "Please fill in at least your email and a message.",
      videoFalta: "The audio in this language is not published yet. Playing the original track with subtitles in your language."
    },
    pt: {
      sinBackend: "Escreva para vieraschiavi@gmail.com e combinamos a demo.",
      emailInvalido: "Digite um e-mail válido.",
      enviando: "Enviando…",
      demoPedida: "Recebemos o seu pedido. Escrevemos para combinar a demo.",
      demoFalta: "Preencha nome, empresa e país: a demo é pessoal e precisamos saber com quem falamos.",
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
      var valor = function (sel) { var e = $(sel); return e ? (e.value || "").trim() : ""; };
      var email = valor("#demo-email");
      var pedido = {
        email: email,
        nombre: valor("#demo-nombre"),
        empresa: valor("#demo-empresa"),
        pais: valor("#demo-pais"),
        mensaje: valor("#demo-mensaje")
      };

      if (!emailValido(email)) { msg.textContent = t.emailInvalido; return; }
      if (!pedido.nombre || !pedido.empresa || !pedido.pais) {
        msg.textContent = t.demoFalta; return;
      }
      if (!BACKEND) { msg.textContent = t.sinBackend; return; }

      msg.textContent = t.enviando;
      // /demo/solicitar sólo REGISTRA el pedido. La demo ya no se entrega
      // sola contra un email: la habilita el dueño después de la reunión, que
      // es lo que evita regalarle el producto a cualquiera que pase.
      fetch(BACKEND + "/demo/solicitar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(pedido)
      }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
      }).then(function (res) {
        if (res.ok) {
          msg.textContent = t.demoPedida;
          formDemo.reset();
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
