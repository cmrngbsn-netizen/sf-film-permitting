"""Browser-side behavior for stars and text boxes on the drawing map.

Leaflet's draw tool only knows plain pins. This script gives each marker its real look
(a numbered star, or the text box with its own words), lets the user click a marker to
write in it, resize it or switch its kind, and stores those details on the marker so they
come back to the app with the drawing (streamlit-folium sends each shape's properties)."""

import json

from branca.element import MacroElement
from jinja2 import Template

# Text box font sizes on screen, in pixels; the PDF uses larger ones (core.pdf.TEXT_PX).
SCREEN_PX = {"Small": 11, "Medium": 14, "Large": 18, "X-Large": 24}


class MarkerTools(MacroElement):
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function () {
          var map = {{ this._parent.get_name() }}, group = {{ this.group.get_name() }};
          var KIND = {{ this.kind }}, SIZES = {{ this.sizes }}, PX = {{ this.px }};
          var saved = {{ this.saved }};  // details of the saved markers, in map order

          var i = 0;
          group.eachLayer(function (layer) {
            if (layer instanceof L.Marker) {
              layer.feature = {type: "Feature", properties: Object.assign({}, saved[i++])};
            }
          });

          function esc(t) {
            return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
          }

          function iconFor(p, n) {
            if (p.kind === "Star") {
              return L.divIcon({className: "", iconSize: [36, 30], iconAnchor: [14, 15], html:
                '<div style="position:relative;font-size:28px;line-height:28px;color:#ff8c00;' +
                'text-shadow:0 0 2px #5a3200">&#9733;<span style="position:absolute;left:22px;' +
                'top:-6px;font:bold 11px sans-serif;color:#000;background:#fff;border:1px solid #333;' +
                'border-radius:7px;padding:0 3px">' + n + '</span></div>'});
            }
            var empty = !(p.text || "").trim();
            var label = empty ? "Text box " + n + " (click to write)" : esc(p.text);
            return L.divIcon({className: "", iconSize: [0, 0], iconAnchor: [0, 0], html:
              '<div style="position:absolute;transform:translate(-50%,-50%);white-space:pre;' +
              'background:white;color:black;cursor:pointer;padding:2px 6px;font:bold ' +
              (PX[p.size] || 14) + 'px sans-serif;border:2px ' +
              (empty ? 'dashed #777' : 'solid #282828') + '">' + label + '</div>'});
          }

          function refresh() {
            var n = 0;
            group.eachLayer(function (l) {
              if (l instanceof L.Marker && l.feature) { n++; l.setIcon(iconFor(l.feature.properties, n)); }
            });
          }

          function options(values, current) {
            return values.map(function (v) {
              return '<option' + (v === current ? ' selected' : '') + '>' + v + '</option>';
            }).join("");
          }

          function attach(layer) {
            layer.bindPopup(function () {
              var p = layer.feature.properties;
              return '<div style="min-width:230px;font:13px sans-serif">' +
                '<label>Kind <select class="mk-kind">' + options(["Star", "Text box"], p.kind) +
                '</select></label>' +
                '<textarea class="mk-text" rows="3" style="width:100%;margin:6px 0;box-sizing:border-box" ' +
                'placeholder="Words for this text box">' + esc(p.text || "") + '</textarea>' +
                '<label>Size <select class="mk-size">' + options(SIZES, p.size) + '</select></label>' +
                '<button class="mk-save" style="float:right">Save</button></div>';
            }, {minWidth: 240});
            layer.on("popupopen", function (e) {
              var el = e.popup.getElement();
              el.querySelector(".mk-save").onclick = function () {
                // A new object, not edits in place: streamlit-folium only sends a change when
                // the drawing differs from its last copy, and that copy shares this object.
                layer.feature.properties = {
                  kind: el.querySelector(".mk-kind").value,
                  text: el.querySelector(".mk-text").value,
                  size: el.querySelector(".mk-size").value,
                };
                layer.closePopup();
                refresh();
                // Tell streamlit-folium the drawing changed, so the app gets the new details.
                map.fire("draw:edited", {layers: L.layerGroup([layer])});
              };
            });
          }

          group.eachLayer(function (l) { if (l instanceof L.Marker) attach(l); });
          map.on("draw:created", function (e) {
            if (e.layerType !== "marker") return;
            e.layer.feature = {type: "Feature", properties: {kind: KIND, text: "", size: "Medium"}};
            attach(e.layer);
            setTimeout(function () {
              refresh();
              if (KIND === "Text box") e.layer.openPopup();
            }, 0);
          });
          refresh();
        })();
        {% endmacro %}
    """)

    def __init__(self, group, markers, kind, sizes):
        super().__init__()
        self._name = "MarkerTools"
        # Element names are looked up when the map is rendered (streamlit-folium renames
        # elements before that), so the script always points at the right map and layer.
        self.group = group
        self.kind = json.dumps(kind)
        self.sizes = json.dumps(sizes)
        self.px = json.dumps(SCREEN_PX)
        # "</" is escaped so words like "</script>" in a text box can't end the script early.
        self.saved = json.dumps([{"kind": mk.kind, "text": mk.text, "size": mk.size}
                                 for mk in markers]).replace("</", "<\\/")
