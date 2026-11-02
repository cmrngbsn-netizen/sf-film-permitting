"""Browser-side behavior for the maps.

Leaflet's draw tool only knows plain lines and pins, and puts its buttons on the map. This
script:
  - puts every control in a panel beside the map instead (tools, curb color, lock, zoom,
    address search, undo, clear), and switches the map into a tool as soon as it is picked;
  - tags every shape with its details (a line's kind and color; a marker's kind, words,
    size and border color), so they come back to the app with the drawing
    (streamlit-folium sends each shape's GeoJSON properties);
  - draws arrowheads as part of the arrow's own SVG line, so the tip stays on the line;
  - shows stars as numbered stars and text boxes as the boxes themselves;
  - gives text boxes an editor (words, a size slider with live preview, border color,
    delete) that opens when one is placed or clicked;
  - zooms only on a pinch (or Ctrl + scroll), so scrolling the page past the map doesn't zoom it."""

import json

from branca.element import MacroElement
from jinja2 import Template

from core.request import ARROW_COLOR
from core.streets import STREET_TYPES

# Turns a Leaflet polyline into an arrow: an SVG marker at the end of its path, rotated with
# the last segment by the browser. The head's tip sits 4px past the last point, where the
# head is wide enough to cover the line's square end.
ARROW_JS = """
function sfArrow(line) {
  var path = line._path;
  if (!path) return;
  var svg = path.ownerSVGElement, ns = "http://www.w3.org/2000/svg";
  if (!svg.querySelector("#sf-head")) {
    var defs = svg.querySelector("defs") || svg.insertBefore(document.createElementNS(ns, "defs"), svg.firstChild);
    var m = document.createElementNS(ns, "marker"), head = document.createElementNS(ns, "path");
    var at = {id: "sf-head", viewBox: "0 0 18 16", markerWidth: 18, markerHeight: 16, refX: 14, refY: 8,
              orient: "auto", markerUnits: "userSpaceOnUse"};
    for (var k in at) m.setAttribute(k, at[k]);
    head.setAttribute("d", "M0 0 L18 8 L0 16 Z");
    head.setAttribute("fill", "%s");
    m.appendChild(head);
    defs.appendChild(m);
  }
  path.setAttribute("marker-end", "url(#sf-head)");
}
""" % ARROW_COLOR

STYLE = """
.leaflet-draw{display:none}
.sf-wrap{display:flex!important;width:100%!important;gap:8px}
.sf-wrap>#map_div{flex:1 1 auto;width:auto!important;min-width:0;border-radius:10px}
.sf-panel{flex:0 0 188px;box-sizing:border-box;padding:10px;background:#f5f5f7;border:1px solid #e1e1e6;
  border-radius:12px;font:13px -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  color:#1d1d1f;overflow-y:auto;display:flex;flex-direction:column;gap:7px}
.sf-sec{font-size:10.5px;font-weight:700;color:#6e6e73;text-transform:uppercase;letter-spacing:.05em;margin-top:3px}
.sf-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px}
.sf-panel button{border:1px solid #d2d2d7;background:#fff;border-radius:8px;padding:6px 7px;
  font:600 12px -apple-system,Helvetica,Arial,sans-serif;color:#1d1d1f;cursor:pointer;text-align:left;
  white-space:nowrap}
.sf-panel button:hover{border-color:#0071e3}
.sf-panel button:disabled{opacity:.4;cursor:default;border-color:#d2d2d7}
.sf-panel button.sf-on{background:#0071e3;border-color:#0071e3;color:#fff}
.sf-panel button.sf-erase.sf-on,.sf-panel button.sf-arm{background:#d70015;border-color:#d70015;color:#fff}
.sf-panel button.sf-wide{grid-column:span 2;text-align:center}
.sf-colors{display:flex;gap:6px;flex-wrap:wrap}
.sf-panel .sf-swatch{width:22px;height:22px;padding:0;border-radius:50%;border:2px solid #fff;
  box-shadow:0 0 0 1px #c7c7cc}
.sf-panel .sf-swatch.sf-on{box-shadow:0 0 0 2px #0071e3}
.sf-hint{background:#fff;border:1px solid #e1e1e6;border-radius:8px;padding:7px 8px;font-size:12px;
  line-height:1.35;color:#3a3a3c}
.sf-hint .sf-acts{display:flex;gap:5px;margin-top:6px}
.sf-hint .sf-acts button{flex:1;text-align:center}
.sf-search{display:flex;gap:4px}
.sf-search input{flex:1;min-width:0;border:1px solid #d2d2d7;border-radius:8px;padding:6px 7px;font:12px -apple-system,Helvetica,Arial,sans-serif;outline:none}
.sf-search input:focus{border-color:#0071e3;box-shadow:0 0 0 3px rgba(0,113,227,.18)}
.sf-found{font-size:11px;color:#6e6e73;line-height:1.3}
.sf-zoom{display:flex;gap:5px}
.sf-zoom button{flex:1;text-align:center}
.sf-drawing .leaflet-marker-icon:not(.leaflet-mouse-marker):not(.leaflet-editing-icon){pointer-events:none}
.sf-erasing .leaflet-interactive{cursor:pointer!important}
.sf-doomed{stroke:#ff3b30;stroke-dasharray:7 5}
.sf-erasing .sf-box:hover,.sf-erasing .sf-star:hover{opacity:.5;outline:2px dashed #ff3b30;outline-offset:3px}
.sf-box{position:absolute;transform:translate(-50%,-50%);white-space:pre;background:#fff;
  color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  font-weight:650;line-height:1.2;letter-spacing:.01em;padding:.35em .75em;border:2px solid;
  border-radius:7px;box-shadow:0 3px 8px rgba(0,0,0,.28);cursor:pointer}
.sf-box.sf-empty{border-style:dashed;color:#6e6e73;font-weight:500;box-shadow:none}
.sf-star{position:relative;font-size:28px;line-height:28px;color:#ff8c00;
  text-shadow:0 1px 2px rgba(90,50,0,.6)}
.sf-badge{position:absolute;left:21px;top:-7px;font:700 10px/14px -apple-system,Helvetica,Arial,sans-serif;
  color:#fff;background:#1d1d1f;border-radius:7px;padding:0 5px}
.sf-popup .leaflet-popup-content-wrapper{border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.25)}
.sf-popup .leaflet-popup-content{margin:14px 16px}
.sf-editor{width:250px;font:13px -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:#1d1d1f}
.sf-editor textarea{width:100%;box-sizing:border-box;border:1px solid #d2d2d7;border-radius:8px;
  padding:8px;font:600 14px -apple-system,Helvetica,Arial,sans-serif;resize:vertical;outline:none}
.sf-editor textarea:focus{border-color:#0071e3;box-shadow:0 0 0 3px rgba(0,113,227,.18)}
.sf-row{display:flex;align-items:center;gap:8px;margin-top:10px}
.sf-row label{width:46px;color:#6e6e73;font-size:12px}
.sf-row input[type=range]{flex:1;accent-color:#0071e3}
.sf-size-val{width:34px;text-align:right;color:#6e6e73;font-size:12px}
.sf-editor .sf-swatch{width:20px;height:20px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #c7c7cc;
  cursor:pointer;padding:0}
.sf-editor .sf-swatch.sf-on{box-shadow:0 0 0 2px #0071e3}
.sf-actions{display:flex;justify-content:space-between;margin-top:14px}
.sf-actions button{border:0;border-radius:8px;padding:6px 14px;font:600 13px -apple-system,Helvetica,Arial,sans-serif;cursor:pointer}
.sf-save{background:#0071e3;color:#fff}
.sf-delete{background:transparent;color:#d70015}
"""

HINTS = {
    "move": "Drag to move the map. Pinch (or Ctrl + scroll) or use + / &minus; to zoom. "
            "Click a text box to edit it.",
    "curb": "Click along the curb. Click the last point again (or <b>Finish</b>) to end the line. "
            "Lines can turn corners.",
    "arrow": "Click from a text box or star to the line it points at. The head goes at the last "
             "point. Click it again (or <b>Finish</b>) to end.",
    "star": "Click the map to drop a star.",
    "text": "Click the map to place a text box, then type in it.",
    "reshape": "Drag a line's white squares, or a star or text box, to move it.",
    "erase": "Click anything on the map to delete it.",
}


class MapTools(MacroElement):
    _template = Template(r"""
        {% macro script(this, kwargs) %}
        (function () {
          // Styles go in from the script, since streamlit-folium passes on only the map script.
          if (!document.getElementById("sf-style")) {
            var css = document.createElement("style");
            css.id = "sf-style";
            css.textContent = {{ this.style }};
            document.head.appendChild(css);
          }
          {{ this.arrow_js }}
          var map = {{ this._parent.get_name() }}, group = {{ this.group.get_name() }};
          var PALETTE = {{ this.palette }}, ARROW = {{ this.arrow }}, TEXT_COLOR = {{ this.text_color }};
          var PX = {{ this.px }}, HINTS = {{ this.hints }};
          var savedLines = {{ this.saved_lines }}, savedMarks = {{ this.saved_marks }};

          function load(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
          function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
          var tool = "move", color = load("sf-color", PALETTE[0][1]), locked = load("sf-locked", "0") === "1";
          if (!PALETTE.some(function (p) { return p[1] === color; })) color = PALETTE[0][1];
          var handler = null, again = false, added = [], found = L.layerGroup().addTo(map);
          var ghosts = L.layerGroup().addTo(map);  // wide, invisible click targets for erasing lines

          // Saved shapes were added in order: lines (curbs, then arrows), then markers.
          var li = 0, mi = 0;
          group.eachLayer(function (layer) {
            var saved = layer instanceof L.Marker ? savedMarks[mi++] : savedLines[li++];
            layer.feature = {type: "Feature", properties: Object.assign({}, saved)};
          });

          function esc(t) {
            return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
          }

          function iconFor(p, n) {
            if (p.kind === "Star") {
              return L.divIcon({className: "", iconSize: [36, 30], iconAnchor: [14, 15],
                html: '<div class="sf-star">&#9733;<span class="sf-badge">' + n + '</span></div>'});
            }
            var empty = !(p.text || "").trim();
            return L.divIcon({className: "", iconSize: [0, 0], iconAnchor: [0, 0],
              html: '<div class="sf-box' + (empty ? ' sf-empty' : '') + '" style="font-size:' + p.size +
                    'px;border-color:' + p.color + '">' +
                    (empty ? 'Text box ' + n + ' &middot; click to write' : esc(p.text)) + '</div>'});
          }

          function refresh() {
            var n = 0;
            group.eachLayer(function (l) {
              if (!l.feature) return;
              if (l instanceof L.Marker) { n++; l.setIcon(iconFor(l.feature.properties, n)); }
              else if (l.feature.properties.kind === "arrow") sfArrow(l);
            });
          }

          function changed(layer, type) {
            // Tell streamlit-folium the drawing changed, so the app gets the new details.
            map.fire(type, {layers: L.layerGroup([layer])});
          }

          function remove(layer) {
            if (layer.editing && layer.editing.enabled()) layer.editing.disable();
            layer.closePopup && layer.closePopup();
            group.removeLayer(layer);
            refresh();
            if (tool === "erase") eraseTargets();
            changed(layer, "draw:deleted");
          }

          // Lines are only a few pixels wide, so the eraser gets a 24px-wide target over each,
          // and the line turns red and dashed while the pointer is on it.
          function eraseTargets() {
            ghosts.clearLayers();
            group.eachLayer(function (l) {
              if (l instanceof L.Marker) return;
              var g = L.polyline(l.getLatLngs(), {weight: 24, opacity: 0, lineCap: "round"}).addTo(ghosts);
              g.on("mouseover", function () { l._path.classList.add("sf-doomed"); });
              g.on("mouseout", function () { l._path.classList.remove("sf-doomed"); });
              g.on("click", function () { remove(l); });
            });
          }

          // ---- Text box editor ----
          function editorHtml(p) {
            var swatches = PALETTE.map(function (c) {
              return '<button type="button" class="sf-swatch' + (c[1] === p.color ? ' sf-on' : '') +
                     '" data-color="' + c[1] + '" title="' + c[0] + '" style="background:' + c[1] + '"></button>';
            }).join("");
            return '<div class="sf-editor">' +
              '<textarea class="sf-text" rows="3" placeholder="Words for this text box">' +
              esc(p.text || "") + '</textarea>' +
              '<div class="sf-row"><label>Size</label><input class="sf-size" type="range" min="' +
              PX.min + '" max="' + PX.max + '" value="' + p.size + '"><span class="sf-size-val">' +
              p.size + 'px</span></div>' +
              '<div class="sf-row"><label>Border</label>' + swatches + '</div>' +
              '<div class="sf-actions"><button type="button" class="sf-delete">Delete</button>' +
              '<button type="button" class="sf-save">Save</button></div></div>';
          }

          function attachEditor(layer) {
            layer.bindPopup(function () { return editorHtml(layer.feature.properties); },
                            {className: "sf-popup", minWidth: 250, maxWidth: 280});
            // Open it ourselves, so a click with the eraser deletes instead.
            layer.off("click", layer._openPopup);
            layer.on("click", function () { if (tool === "move" || tool === "reshape") openEditor(layer); });
            layer.on("popupopen", function (e) {
              var el = e.popup.getElement(), p = layer.feature.properties;
              var draft = {kind: p.kind, text: p.text || "", size: p.size, color: p.color};
              var n = 0, mine = 0;
              group.eachLayer(function (l) { if (l instanceof L.Marker) { n++; if (l === layer) mine = n; } });
              function preview() { layer.setIcon(iconFor(draft, mine)); }
              el.querySelector(".sf-text").oninput = function () { draft.text = this.value; preview(); };
              el.querySelector(".sf-size").oninput = function () {
                draft.size = +this.value;
                el.querySelector(".sf-size-val").textContent = this.value + "px";
                preview();
              };
              el.querySelectorAll(".sf-swatch").forEach(function (b) {
                b.onclick = function () {
                  draft.color = b.dataset.color;
                  el.querySelectorAll(".sf-swatch").forEach(function (o) { o.classList.toggle("sf-on", o === b); });
                  preview();
                };
              });
              el.querySelector(".sf-save").onclick = function () {
                // A new object, not edits in place: streamlit-folium only sends a change when
                // the drawing differs from its last copy, and that copy shares the old object.
                layer.feature.properties = draft;
                layer.closePopup();
                refresh();
                changed(layer, "draw:edited");
              };
              el.querySelector(".sf-delete").onclick = function () { remove(layer); };
              setTimeout(function () { el.querySelector(".sf-text").focus(); }, 0);
            });
            layer.on("popupclose", function () {
              refresh();  // drop an unsaved preview
              if (tool === "text" && !handler) startDraw();  // ready for the next text box
            });
          }

          function openEditor(layer) {
            layer.getPopup().options.autoPan = !locked;  // a locked map stays where it is
            layer.openPopup();
          }

          function watch(layer) {
            layer.on("edit dragend", function () { refresh(); changed(layer, "draw:edited"); });
            if (layer instanceof L.Marker && layer.feature.properties.kind !== "Star") attachEditor(layer);
          }
          group.eachLayer(watch);
          group.on("click", function (e) {
            if (tool === "erase") remove(e.propagatedFrom || e.layer);
          });

          // ---- The panel beside the map ----
          var box = map.getContainer();
          box.parentNode.classList.add("sf-wrap");
          var panel = document.createElement("div");
          panel.className = "sf-panel";
          var TOOLS = [["move", "&#9995; Move map"], ["curb", "&#9473; Curb line"], ["arrow", "&#10140; Arrow"],
                       ["star", "&#9733; Star"], ["text", "&#9645; Text box"], ["reshape", "&#10021; Reshape"],
                       ["erase", "&#9003; Erase"]];
          panel.innerHTML =
            '<div class="sf-sec">Tools</div><div class="sf-grid">' +
            TOOLS.map(function (t) {
              return '<button type="button" data-tool="' + t[0] + '"' + (t[0] === "erase" ? ' class="sf-erase"' : '') +
                     '>' + t[1] + '</button>';
            }).join("") + '<button type="button" class="sf-undo">&#8630; Undo</button></div>' +
            '<div class="sf-hint"></div>' +
            '<div class="sf-sec">Curb line color</div><div class="sf-colors">' +
            PALETTE.map(function (c) {
              return '<button type="button" class="sf-swatch" data-color="' + c[1] + '" title="' + c[0] +
                     '" style="background:' + c[1] + '"></button>';
            }).join("") + '</div>' +
            '<div class="sf-sec">Map</div>' +
            '<div class="sf-zoom"><button type="button" class="sf-lock"></button>' +
            '<button type="button" class="sf-in" title="Zoom in">+</button>' +
            '<button type="button" class="sf-out" title="Zoom out">&minus;</button></div>' +
            '<form class="sf-search"><input placeholder="Search an address" aria-label="Search an address">' +
            '<button type="submit">Go</button></form><div class="sf-found"></div>' +
            '<div class="sf-sec">Start over</div>' +
            '<button type="button" class="sf-clear">Clear everything</button>';
          box.parentNode.insertBefore(panel, box);
          map.invalidateSize();
          var $ = function (s) { return panel.querySelector(s); };

          function showTool() {
            panel.querySelectorAll("[data-tool]").forEach(function (b) {
              b.classList.toggle("sf-on", b.dataset.tool === tool);
            });
            box.classList.toggle("sf-erasing", tool === "erase");
            // While drawing, clicks on stars and text boxes go to the map, so an arrow can start on one.
            box.classList.toggle("sf-drawing", ["curb", "arrow", "star", "text"].indexOf(tool) >= 0);
            var drawsLine = tool === "curb" || tool === "arrow";
            $(".sf-hint").innerHTML = HINTS[tool] + (drawsLine ?
              '<div class="sf-acts"><button type="button" class="sf-finish">Finish</button>' +
              '<button type="button" class="sf-cancel">Cancel</button></div>' : "");
            if (drawsLine) {
              $(".sf-finish").onclick = function () { if (handler && handler.completeShape) handler.completeShape(); };
              $(".sf-cancel").onclick = function () { setTool("move"); };
            }
            panel.querySelectorAll(".sf-colors .sf-swatch").forEach(function (b) {
              b.classList.toggle("sf-on", b.dataset.color === color);
            });
          }

          function startDraw() {
            if (tool === "curb" || tool === "arrow") {
              handler = new L.Draw.Polyline(map, {shapeOptions: {stroke: true, fill: false, clickable: true,
                color: tool === "arrow" ? ARROW : color, weight: tool === "arrow" ? 4 : 5, opacity: 0.9,
                lineCap: tool === "arrow" ? "butt" : "round"}});
            } else {
              handler = new L.Draw.Marker(map, {icon: tool === "star" ? iconFor({kind: "Star"}, "+") :
                iconFor({kind: "Text box", text: "", size: PX["default"], color: TEXT_COLOR}, "")});
            }
            handler.enable();
          }

          function stopTool() {
            if (handler) { var h = handler; handler = null; h.disable(); }
            if (tool === "reshape") {
              group.eachLayer(function (l) {
                if (l instanceof L.Marker) l.dragging && l.dragging.disable();
                else if (l.editing) l.editing.disable();
              });
            }
            ghosts.clearLayers();
          }

          function setTool(t) {
            stopTool();
            map.closePopup();
            tool = t;
            if (["curb", "arrow", "star", "text"].indexOf(t) >= 0) startDraw();
            if (t === "erase") eraseTargets();
            if (t === "reshape") {
              group.eachLayer(function (l) {
                if (l instanceof L.Marker) l.dragging && l.dragging.enable();
                else if (l.editing) l.editing.enable();
              });
            }
            showTool();
          }

          panel.querySelectorAll("[data-tool]").forEach(function (b) {
            b.onclick = function () { setTool(b.dataset.tool); };
          });
          panel.querySelectorAll(".sf-colors .sf-swatch").forEach(function (b) {
            b.onclick = function () {
              color = b.dataset.color;
              store("sf-color", color);
              if (tool === "curb" && handler) {  // recolor the line being drawn
                handler.options.shapeOptions.color = color;
                if (handler._poly) handler._poly.setStyle({color: color});
                showTool();
              } else {
                setTool("curb");  // picking a color means drawing a curb line
              }
            };
          });

          // Undo: the last point of the line being drawn, else the last shape added here.
          $(".sf-undo").onclick = function () {
            if (handler && handler._markers && handler._markers.length) { handler.deleteLastVertex(); return; }
            while (added.length) {
              var l = added.pop();
              if (group.hasLayer(l)) { remove(l); return; }
            }
          };

          // Clear everything takes a second click, so it can't happen by accident.
          var armed = null;
          function disarm() {
            clearTimeout(armed); armed = null;
            $(".sf-clear").classList.remove("sf-arm");
            $(".sf-clear").textContent = "Clear everything";
          }
          $(".sf-clear").onclick = function () {
            if (!armed) {
              this.classList.add("sf-arm");
              this.textContent = "Click again to clear";
              armed = setTimeout(disarm, 3000);
              return;
            }
            disarm();
            setTool("move");
            var all = group.getLayers();
            if (!all.length) return;
            all.forEach(function (l) { group.removeLayer(l); });
            map.fire("draw:deleted", {layers: L.layerGroup(all)});
          };

          // Lock keeps the map still while placing things; drawing still works.
          function applyLock() {
            ["dragging", "touchZoom", "doubleClickZoom", "boxZoom", "keyboard"].forEach(function (h) {
              if (map[h]) locked ? map[h].disable() : map[h].enable();
            });
            $(".sf-lock").innerHTML = locked ? "&#128274; Locked" : "&#128275; Lock";
            $(".sf-lock").classList.toggle("sf-on", locked);
            $(".sf-in").disabled = $(".sf-out").disabled = locked;
          }
          $(".sf-lock").onclick = function () { locked = !locked; store("sf-locked", locked ? "1" : "0"); applyLock(); };
          $(".sf-in").onclick = function () { map.zoomIn(); };
          $(".sf-out").onclick = function () { map.zoomOut(); };

          // Plain scrolling passes over the map to the page; a pinch (Ctrl + scroll) zooms.
          var wheel = 0;
          box.addEventListener("wheel", function (e) {
            if (!e.ctrlKey) return;
            e.preventDefault();
            if (locked) return;
            wheel += e.deltaY;
            if (Math.abs(wheel) >= 40) {
              map.setZoomAround(map.mouseEventToContainerPoint(e), map.getZoom() + (wheel < 0 ? 1 : -1));
              wheel = 0;
            }
          }, {passive: false});

          // Search: "Grant & Washington" from the city's intersection list (static/, served
          // next to the app), anything else from OpenStreetMap's Nominatim, limited to SF.
          var TYPES = {{ this.street_types }}, crossings = null;
          function key(name) {  // same as core.streets.street_key
            var w = name.toUpperCase().replace(/[.']/g, "").replace(/\b0+(\d)/g, "$1").trim().split(/\s+/);
            while (w.length > 1 && TYPES.indexOf(w[w.length - 1]) >= 0) w.pop();
            return w.join(" ");
          }
          function crossing(a, b) {
            crossings = crossings || fetch("../../app/static/intersections.json").then(function (r) { return r.json(); });
            return crossings.then(function (data) {
              function streets(part) {
                var k = key(part), exact = [], start = [];
                data.streets.forEach(function (s, i) {
                  if (s[1] === k) exact.push(i); else if (s[1].indexOf(k) === 0) start.push(i);
                });
                return exact.length ? exact : start;
              }
              var as = streets(a), bs = streets(b);
              for (var i = 0; i < data.nodes.length; i++) {
                var n = data.nodes[i];
                var hitA = n[0].filter(function (s) { return as.indexOf(s) >= 0; });
                var hitB = n[0].filter(function (s) { return bs.indexOf(s) >= 0 && hitA.indexOf(s) < 0; });
                if (hitA.length && hitB.length) {
                  return {ll: [n[1], n[2]], name: data.streets[hitA[0]][0] + " & " + data.streets[hitB[0]][0]};
                }
              }
              return null;
            });
          }
          function nominatim(q) {
            return fetch("https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&bounded=1" +
                         "&viewbox=-122.53,37.84,-122.35,37.70&q=" + encodeURIComponent(q))
              .then(function (r) { return r.json(); })
              .then(function (res) {
                return res.length ? {ll: [+res[0].lat, +res[0].lon],
                                     name: res[0].display_name.split(",").slice(0, 3).join(",")} : null;
              });
          }
          $(".sf-search").onsubmit = function (e) {
            e.preventDefault();
            var q = $(".sf-search input").value.trim();
            if (!q) return;
            $(".sf-found").textContent = "Searching...";
            var parts = q.split(/\s*(?:&|@|\/|\band\b|\bat\b)\s*/i).filter(Boolean);
            var look = parts.length === 2 ?
              crossing(parts[0], parts[1]).then(function (hit) { return hit || nominatim(q); }) : nominatim(q);
            look.then(function (hit) {
              found.clearLayers();
              if (!hit) { $(".sf-found").textContent = "Not found in San Francisco."; return; }
              map.setView(hit.ll, 18);
              found.addLayer(L.circleMarker(hit.ll, {radius: 9, color: "#0071e3", weight: 3, fillOpacity: 0.2,
                                                     interactive: false}));
              $(".sf-found").textContent = hit.name;
            }).catch(function () { $(".sf-found").textContent = "Search isn't available right now."; });
          };

          map.on("draw:created", function (e) {
            again = true;
            var layer = e.layer;
            if (e.layerType === "marker") {
              layer.feature = {type: "Feature", properties: tool === "star" ? {kind: "Star", text: "", size: PX["default"], color: TEXT_COLOR} :
                {kind: "Text box", text: "", size: PX["default"], color: TEXT_COLOR}};
            } else {
              layer.feature = {type: "Feature", properties: {kind: tool === "arrow" ? "arrow" : "curb",
                                                             color: tool === "arrow" ? ARROW : color}};
            }
            watch(layer);
            added.push(layer);
            setTimeout(function () {
              refresh();
              if (layer.feature.properties.kind === "Text box") openEditor(layer);
            }, 0);
          });
          map.on("draw:drawstop", function () {
            if (locked) map.doubleClickZoom.disable();  // drawing turns it back on
            if (!handler) return;  // stopped by switching tools
            if (!again) { handler = null; setTool("move"); return; }  // cancelled with Escape
            again = false;
            if (tool === "text") { handler = null; return; }  // the next one starts when its editor closes
            setTimeout(startDraw, 0);  // keep drawing with the same tool
          });

          applyLock();
          showTool();
          refresh();
        })();
        {% endmacro %}
    """)

    def __init__(self, group, lines, arrows, markers, palette, text_color, px):
        super().__init__()
        self._name = "MapTools"
        # Element names are looked up when the map is rendered (streamlit-folium renames
        # elements before that), so the script always points at the right map and layer.
        self.group = group
        self.style = json.dumps(STYLE)
        self.arrow_js = ARROW_JS
        self.palette = json.dumps(list(palette.items()))
        self.arrow = json.dumps(ARROW_COLOR)
        self.text_color = json.dumps(text_color)
        self.px = json.dumps(px)
        self.hints = json.dumps(HINTS)
        self.street_types = json.dumps(sorted(STREET_TYPES))
        self.saved_lines = json.dumps([{"kind": "curb", "color": ln.color} for ln in lines]
                                      + [{"kind": "arrow", "color": ARROW_COLOR} for _ in arrows])
        # "</" is escaped so words like "</script>" in a text box can't end the script early.
        self.saved_marks = json.dumps([{"kind": m.kind, "text": m.text, "size": m.size, "color": m.color}
                                       for m in markers]).replace("</", "<\\/")


class ArrowHeads(MacroElement):
    """Arrowheads for arrows on a map without the drawing tools (the review map)."""
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function () {
          {{ this.arrow_js }}
          {% for line in this.lines %}sfArrow({{ line.get_name() }});
          {% endfor %}
        })();
        {% endmacro %}
    """)

    def __init__(self, lines):
        super().__init__()
        self._name = "ArrowHeads"
        self.arrow_js = ARROW_JS
        self.lines = lines
