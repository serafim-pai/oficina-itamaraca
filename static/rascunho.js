// Rascunho automático: guarda no navegador o que foi digitado nos formulários marcados com
// data-rascunho e devolve tudo se a página for fechada antes de enviar. Não guarda fotos nem o token.
(function () {
    var VALIDADE = 3 * 24 * 3600 * 1000;      // rascunho velho (3 dias) é descartado

    function campos(form) {
        return Array.prototype.filter.call(form.elements, function (c) {
            return c.name && c.name !== "csrf_token" && c.type !== "hidden" && c.type !== "file" &&
                   c.type !== "submit" && c.type !== "button" && c.type !== "password";
        });
    }

    function iniciar(form) {
        var chave = "rascunho:" + location.pathname + ":" + form.getAttribute("data-rascunho");
        var lista = campos(form);

        function valores() {
            var v = {};
            lista.forEach(function (c) { v[c.name] = c.type === "checkbox" ? c.checked : c.value; });
            return v;
        }
        function temConteudo(v) {
            return Object.keys(v).some(function (k) { return v[k] === true || (v[k] && v[k] !== "") });
        }
        function guardar() {
            try {
                var v = valores();
                if (temConteudo(v)) { localStorage.setItem(chave, JSON.stringify({hora: Date.now(), v: v})); }
                else { localStorage.removeItem(chave); }
            } catch (e) {}
        }
        function apagar() { try { localStorage.removeItem(chave); } catch (e) {} }

        // devolve o rascunho, mas só se o formulário estiver vazio (não atropela o que o servidor devolveu)
        try {
            var salvo = JSON.parse(localStorage.getItem(chave) || "null");
            if (salvo && Date.now() - salvo.hora > VALIDADE) { apagar(); salvo = null; }
            if (salvo && !temConteudo(valores())) {
                lista.forEach(function (c) {
                    if (!(c.name in salvo.v)) { return; }
                    if (c.type === "checkbox") { c.checked = !!salvo.v[c.name]; } else { c.value = salvo.v[c.name]; }
                });
                var detalhes = form.closest("details");
                if (detalhes) { detalhes.open = true; }
                var aviso = document.createElement("div");
                aviso.className = "ok";
                aviso.textContent = "Rascunho recuperado: é o que você já tinha digitado antes de fechar a página. ";
                var botao = document.createElement("button");
                botao.type = "button";
                botao.textContent = "Descartar rascunho";
                botao.style.cssText = "width:auto;margin:6px 0 0;display:block";
                botao.addEventListener("click", function () {
                    apagar();
                    lista.forEach(function (c) { if (c.type === "checkbox") { c.checked = false; } else { c.value = ""; } });
                    aviso.remove();
                });
                aviso.appendChild(botao);
                form.insertBefore(aviso, form.firstChild);
            }
        } catch (e) {}

        form.addEventListener("input", guardar);
        form.addEventListener("change", guardar);
        form.addEventListener("submit", function (ev) { if (!ev.defaultPrevented) { apagar(); } });
        guardar();    // se o servidor devolveu o formulário com erro, o que está na tela volta a ser rascunho
    }

    Array.prototype.forEach.call(document.querySelectorAll("form[data-rascunho]"), iniciar);
})();
