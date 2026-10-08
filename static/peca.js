// Mostra "Qual peça?" e o preço só quando a oficina vai comprar a peça.
(function () {
    Array.prototype.forEach.call(document.querySelectorAll("select[name='situacao']"), function (lista) {
        var campos = lista.form && lista.form.querySelector(".campos-compra");
        if (!campos) { return; }
        function ajustar() { campos.hidden = lista.value !== "OFICINA_COMPRA"; }
        lista.addEventListener("change", ajustar);
        ajustar();
    });
})();
