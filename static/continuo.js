// Página "corrida": depois de salvar algo, a tela volta ao mesmo ponto em que o usuário estava,
// em vez de pular para o topo. Se houver erro no formulário, deixa o aviso aparecer no topo.
(function () {
    var chave = "continuo:" + location.pathname;
    try {
        var salvo = JSON.parse(sessionStorage.getItem(chave) || "null");
        sessionStorage.removeItem(chave);
        if (salvo && Date.now() - salvo.hora < 20000 && !location.hash &&
                !document.querySelector("[data-erro-formulario]")) {
            window.scrollTo(0, salvo.y);
        }
    } catch (e) {}
    document.addEventListener("submit", function (ev) {
        var f = ev.target;
        if (ev.defaultPrevented || !f || (f.method || "").toLowerCase() !== "post") { return; }
        try {
            sessionStorage.setItem(chave, JSON.stringify({y: window.scrollY, hora: Date.now()}));
        } catch (e) {}
    });
})();
