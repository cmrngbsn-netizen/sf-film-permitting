"""Browser-side behavior for the drawing map.

Leaflet's draw tool only knows plain lines and pins. This script:
  - tags every shape with its details (a line's kind and color; a marker's kind, words,
    size and border color), so they come back to the app with the drawing
    (streamlit-folium sends each shape's GeoJSON properties);
  - draws arrowheads on arrows;
  - shows stars as numbered stars and text boxes as the boxes themselves;
  - gives text boxes an editor (words, a size slider with live preview, border color,
    delete) that opens when one is placed or clicked."""

import json

from branca.element import MacroElement
from jinja2 import Template

STYLE = """
.sf-box{position:absolute;transform:translate(-50%,-50%);white-space:pre;background:#fff;
  color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  font-weight:650;line-height:1.2;letter-spacing:.01em;padding:.35em .75em;border:2px solid;
  border-radius:7px;box-shadow:0 3px 8px rgba(0,0,0,.28);cursor:pointer}
.sf-box.sf-empty{border-style:dashed;color:#8a8a8e;font-weight:500;box-shadow:none}
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
.sf-swatch{width:20px;height:20px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #c7c7cc;
  cursor:pointer;padding:0}
.sf-swatch.sf-on{box-shadow:0 0 0 2px #0071e3}
.sf-actions{display:flex;justify-content:space-between;margin-top:14px}
.sf-actions button{border:0;border-radius:8px;padding:6px 14px;font:600 13px -apple-system,Helvetica,Arial,sans-serif;cursor:pointer}
.sf-save{background:#0071e3;color:#fff}
.sf-delete{background:transparent;color:#d70015}
"""


class MapTools(MacroElement):
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function () {
          // Styles go in from the script, since streamlit-folium passes on only the map script.
          if (!document.getElementById("sf-style")) {
            var css = document.createElement("style");
            css.id = "sf-style";
            css.textContent = {{ this.style }};
            document.head.appendChild(css);
          }
          var map = {{ this._parent.get_name() }}, group = {{ this.group.get_name() }};
          var LINE_KIND = {{ this.line_kind }}, COLOR = {{ this.color }}, MARK_KIND = {{ this.mark_kind }};
          var PALETTE = {{ this.palette }}, TEXT_COLOR = {{ this.text_color }}, PX = {{ this.px }};
          var savedLines = {{ this.saved_lines }}, savedMarks = {{ this.saved_marks }};
          var heads = L.layerGroup().addTo(map);

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
                    'px;border-color:' + (empty ? '#9a9a9f' : p.color) + '">' +
                    (empty ? 'Text box ' + n + ' &middot; click to write' : esc(p.text)) + '</div>'});
          }

          function arrowHead(line) {
            var pts = line.getLatLngs();
            if (pts.length < 2) return null;
            var a = map.latLngToLayerPoint(pts[pts.length - 2]), b = map.latLngToLayerPoint(pts[pts.length - 1]);
            var angle = Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI;
            var color = line.feature.properties.color || line.options.color;
            // An 18x16 triangle whose tip sits exactly on the line's last point.
            return L.marker(pts[pts.length - 1], {interactive: false, keyboard: false,
              icon: L.divIcon({className: "", iconSize: [0, 0], iconAnchor: [0, 0], html:
                '<div style="position:absolute;left:-18px;top:-8px;width:18px;height:16px;' +
                'transform-origin:18px 8px;transform:rotate(' + angle + 'deg)">' +
                '<svg width="18" height="16"><path d="M0 0 L18 8 L0 16 Z" fill="' + color + '"/></svg></div>'})});
          }

          function refresh() {
            heads.clearLayers();
            var n = 0;
            group.eachLayer(function (l) {
              if (!l.feature) return;
              if (l instanceof L.Marker) { n++; l.setIcon(iconFor(l.feature.properties, n)); }
              else if (l.feature.properties.kind === "arrow") { var h = arrowHead(l); if (h) heads.addLayer(h); }
            });
          }

          function changed(layer, type) {
            // Tell streamlit-folium the drawing changed, so the app gets the new details.
            map.fire(type, {layers: L.layerGroup([layer])});
          }

          function editorHtml(p) {
            var swatches = PALETTE.map(function (c) {
              return '<button type="button" class="sf-swatch' + (c === p.color ? ' sf-on' : '') +
                     '" data-color="' + c + '" style="background:' + c + '"></button>';
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
              el.querySelector(".sf-delete").onclick = function () {
                layer.closePopup();
                group.removeLayer(layer);
                refresh();
                changed(layer, "draw:deleted");
              };
              setTimeout(function () { el.querySelector(".sf-text").focus(); }, 0);
            });
            layer.on("popupclose", refresh);  // drop an unsaved preview
          }

          group.eachLayer(function (l) {
            if (l instanceof L.Marker && l.feature.properties.kind !== "Star") attachEditor(l);
          });
          map.on("draw:created", function (e) {
            if (e.layerType === "marker") {
              e.layer.feature = {type: "Feature", properties:
                {kind: MARK_KIND, text: "", size: PX["default"], color: TEXT_COLOR}};
              if (MARK_KIND !== "Star") attachEditor(e.layer);
            } else if (e.layerType === "polyline") {
              e.layer.feature = {type: "Feature", properties: {kind: LINE_KIND, color: COLOR}};
            }
            setTimeout(function () {
              refresh();
              if (e.layerType === "marker" && MARK_KIND !== "Star") e.layer.openPopup();
            }, 0);
          });
          map.on("zoomend draw:edited draw:deleted draw:editstop draw:deletestop", refresh);
          refresh();
        })();
        {% endmacro %}
    """)

    def __init__(self, group, lines, arrows, markers, line_kind, color, mark_kind,
                 palette, text_color, px):
        super().__init__()
        self._name = "MapTools"
        # Element names are looked up when the map is rendered (streamlit-folium renames
        # elements before that), so the script always points at the right map and layer.
        self.group = group
        self.style = json.dumps(STYLE)
        self.line_kind = json.dumps(line_kind)
        self.color = json.dumps(color)
        self.mark_kind = json.dumps(mark_kind)
        self.palette = json.dumps(palette)
        self.text_color = json.dumps(text_color)
        self.px = json.dumps(px)
        self.saved_lines = json.dumps([{"kind": "curb", "color": ln.color} for ln in lines]
                                      + [{"kind": "arrow", "color": a.color} for a in arrows])
        # "</" is escaped so words like "</script>" in a text box can't end the script early.
        self.saved_marks = json.dumps([{"kind": m.kind, "text": m.text, "size": m.size, "color": m.color}
                                       for m in markers]).replace("</", "<\\/")
