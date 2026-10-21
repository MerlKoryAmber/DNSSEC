/* MK Themes — выбор темы. Подключать в <head> обычным <script> (без async/defer).

   <html data-theme="gold" data-user="ivanov">
   window.MK_THEMES = { order: [...], default: "gold" }

   mkTheme.get() / set(name) / cycle() / reset() / syncUser(name)
   Личная тема: mk.theme:<user>. Последняя выбранная (и для login): mk.theme:last */
(function () {
    var h = document.documentElement;
    var cfg = window.MK_THEMES || {};
    var order = cfg.order || ["standard", "forest", "steampunk", "gold", "itheme"];
    var def = h.getAttribute("data-theme") || cfg.default || order[0];
    var LAST = "mk.theme:last";

    function key() {
        return "mk.theme:" + (h.getAttribute("data-user") || cfg.user || "");
    }
    function apply(t) {
        h.setAttribute("data-theme", t);
        return t;
    }
    function valid(t) {
        return t && order.indexOf(t) >= 0 ? t : null;
    }
    function store(t) {
        try {
            var k = key();
            if (t) {
                localStorage.setItem(k, t);
                localStorage.setItem(LAST, t);
            } else {
                localStorage.removeItem(k);
            }
        } catch (e) { /* private mode */ }
    }
    function load() {
        try {
            var mine = valid(localStorage.getItem(key()));
            if (mine) return apply(mine);
            var last = valid(localStorage.getItem(LAST));
            if (last) return apply(last);
        } catch (e) { /* ignore */ }
        return apply(def);
    }
    load();
    window.mkTheme = {
        order: order,
        get: function () {
            return h.getAttribute("data-theme") || def;
        },
        set: function (t) {
            if (!valid(t)) return window.mkTheme.get();
            store(t);
            return apply(t);
        },
        cycle: function () {
            return window.mkTheme.set(
                order[(order.indexOf(window.mkTheme.get()) + 1) % order.length]
            );
        },
        reset: function () {
            store(null);
            try { localStorage.removeItem(LAST); } catch (e) { /* ignore */ }
            return apply(def);
        },
        syncUser: function (name) {
            if (name) h.setAttribute("data-user", String(name));
            else h.removeAttribute("data-user");
            return load();
        }
    };
})();
