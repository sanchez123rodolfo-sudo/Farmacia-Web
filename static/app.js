// Lista en memoria que representa el carrito de compras, inicialmente vacía.
const carrito = [];

// Flag para evitar envíos duplicados mientras se procesa una venta
let isProcessingVenta = false;

// Diccionario de productos simulados con nombre y precio base para agregar al carrito.
// Nota: esta lista es mock/por defecto. Aquí es donde debes reemplazar los datos falsos
// por los datos que traigas desde tu backend Python / MySQL.
let productosSimulados = [
  { nombre: "Ibuprofeno 400 mg", precio: 15.5, requiere_receta: false },
  { nombre: "Jarabe para la tos", precio: 24.0, requiere_receta: false },
  { nombre: "Vitaminas C", precio: 18.0, requiere_receta: false },
];

// Función de ejemplo para cargar la lista real desde el backend Python.
// Debe corresponder a un endpoint que ejecute tu SELECT * desde MySQL y devuelva JSON.
async function cargarMedicamentosDesdeBackend() {
  try {
    console.log("[app.js] Cargando medicamentos desde backend: /api/medicamentos");
    const respuesta = await fetch("/api/medicamentos"); // Cambia la ruta según tu backend.
    if (!respuesta.ok) {
      throw new Error(`Error al cargar medicamentos: ${respuesta.status}`);
    }
    const datos = await respuesta.json();
    console.log("[app.js] Respuesta /api/medicamentos:", datos);

    // El backend devuelve { success: true, medicamentos: [...] }
    let lista = [];
    if (Array.isArray(datos)) {
      // caso antiguo: respuesta directa
      lista = datos;
    } else if (datos && Array.isArray(datos.medicamentos)) {
      lista = datos.medicamentos;
    }

    // Normalizar cada elemento para asegurar que tenga nombre y precio
    if (Array.isArray(lista) && lista.length > 0) {
      productosSimulados = lista.map((m) => ({
        nombre: m.nombre || m.producto || "",
        precio: Number(m.precio || m.precio_unitario || 0),
        componente: m.componente || "",
        stock: Number(m.stock || 0),
        requiere_receta: Boolean(m.requiere_receta),
        codigo_barras: m.codigo_barras || null,
        id: m.id || null,
        // Presentaciones dinámicas desde BD: [{id, nombre, factor_conversion, precio}]
        // La venta por 'Unidad' (factor 1) es implícita y siempre está disponible.
        presentaciones: Array.isArray(m.presentaciones)
          ? m.presentaciones.map((p) => ({
              id: Number(p.id),
              nombre: String(p.nombre),
              factor_conversion: Math.max(Number(p.factor_conversion) || 1, 1),
              precio: Number(p.precio || 0),
            }))
          : [],
      }));
      console.log(`[app.js] Cargados ${productosSimulados.length} medicamentos desde backend.`);
    } else {
      console.log("[app.js] No se recibieron medicamentos desde backend, usando fallback local.");
    }
  } catch (error) {
    console.error("No se pudo cargar la lista de medicamentos desde el backend:", error);
    // Aquí puedes mantener los productos simulados como fallback o mostrar un mensaje al usuario.
  }
}

// Simple toast implementation
function showToast(type, message, timeout = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.style.pointerEvents = 'auto';
  toast.style.minWidth = '220px';
  toast.style.padding = '12px 16px';
  toast.style.borderRadius = '10px';
  toast.style.boxShadow = '0 8px 24px rgba(15,23,42,0.12)';
  toast.style.color = '#fff';
  toast.style.fontWeight = '600';
  toast.style.opacity = '0';
  toast.style.transform = 'translateY(-6px)';
  toast.style.transition = 'opacity 240ms, transform 240ms';

  if (type === 'success') toast.style.background = '#15803d';
  else if (type === 'error') toast.style.background = '#dc2626';
  else if (type === 'warning') toast.style.background = '#b91c1c';
  else toast.style.background = '#2563eb';

  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateY(0)';
  });

  // Also announce via aria-live region for screen readers
  try {
    const politeRegion = document.getElementById('aria-live-region');
    const assertiveRegion = document.getElementById('aria-live-assertive');
    if (type === 'error' && assertiveRegion) {
      assertiveRegion.textContent = message;
      setTimeout(() => { if (assertiveRegion.textContent === message) assertiveRegion.textContent = ''; }, timeout + 200);
    } else if (politeRegion) {
      politeRegion.textContent = message;
      setTimeout(() => { if (politeRegion.textContent === message) politeRegion.textContent = ''; }, timeout + 200);
    }
  } catch (e) { /* no-op */ }

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-6px)';
    setTimeout(() => container.removeChild(toast), 260);
  }, timeout);
}

// Muestra un card persistente con botón para enviar comprobante por WhatsApp.
function mostrarBotonWhatsApp(enlaceWA, numeroComprobante) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const card = document.createElement('div');
  card.style.pointerEvents = 'auto';
  card.style.minWidth = '280px';
  card.style.maxWidth = '340px';
  card.style.padding = '16px 18px';
  card.style.borderRadius = '14px';
  card.style.boxShadow = '0 12px 32px rgba(15,23,42,0.18)';
  card.style.background = '#f0fdf4';
  card.style.border = '1.5px solid rgba(34,197,94,0.35)';
  card.style.opacity = '0';
  card.style.transform = 'translateY(-8px)';
  card.style.transition = 'opacity 280ms, transform 280ms';
  card.style.fontFamily = 'inherit';

  card.innerHTML = `
    <div style="font-weight:700;color:#15803d;font-size:0.92rem;margin-bottom:6px;">
      📱 Enviar comprobante por WhatsApp
    </div>
    <div style="font-size:0.82rem;color:#475569;margin-bottom:12px;">
      ${numeroComprobante} — Abre WhatsApp Web con el resumen listo para enviar.
    </div>
    <a href="${enlaceWA}" target="_blank" rel="noopener noreferrer"
       style="display:inline-flex;align-items:center;gap:8px;padding:10px 18px;border-radius:10px;background:#25d366;color:#fff;font-weight:700;font-size:0.9rem;text-decoration:none;transition:background 200ms;">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="#fff"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
      Enviar por WhatsApp
    </a>
    <button id="cerrar-wa-card" style="display:block;margin-top:10px;background:none;border:none;color:#94a3b8;font-size:0.78rem;cursor:pointer;padding:2px 0;">
      Cerrar
    </button>
  `;

  container.appendChild(card);
  requestAnimationFrame(() => {
    card.style.opacity = '1';
    card.style.transform = 'translateY(0)';
  });

  // Cerrar card
  const btnCerrar = card.querySelector('#cerrar-wa-card');
  if (btnCerrar) {
    btnCerrar.addEventListener('click', () => {
      card.style.opacity = '0';
      card.style.transform = 'translateY(-8px)';
      setTimeout(() => { if (card.parentNode) card.parentNode.removeChild(card); }, 300);
    });
  }

  // Auto-cerrar después de 60 segundos
  setTimeout(() => {
    if (card.parentNode) {
      card.style.opacity = '0';
      card.style.transform = 'translateY(-8px)';
      setTimeout(() => { if (card.parentNode) card.parentNode.removeChild(card); }, 300);
    }
  }, 60000);
}

// Referencias a los elementos del DOM necesarios para actualizar la interfaz en tiempo real.
const inputDocumento = document.getElementById("cliente-documento");
const tipoComprobante = document.getElementById("tipo-comprobante");
const carritoBody = document.getElementById("carrito-body");
const opGravadaElemento = document.getElementById("op-gravada");
const igvElemento = document.getElementById("igv");
const totalPagarElemento = document.getElementById("total-pagar");
const buscadorMedicamentos = document.getElementById("buscador-medicamentos");
const resultadosBusqueda = document.getElementById("resultados-busqueda");
const inputCodigoBarras = document.getElementById("codigo-barras-input");
const medioPagoEl = document.getElementById("medio-pago");
const grupoMontoPagado = document.getElementById("grupo-monto-pagado");
const inputMontoPagado = document.getElementById("monto-pagado");
const grupoNumeroOperacion = document.getElementById("grupo-numero-operacion");
const inputNumeroOperacion = document.getElementById("numero-operacion");
const panelYape = document.getElementById("pago-yape");
const panelPlin = document.getElementById("pago-plin");
const panelTarjeta = document.getElementById("pago-tarjeta");
const tipoEnvioEl = document.getElementById("tipo-envio-comprobante");
const grupoContactoDigital = document.getElementById("grupo-contacto-digital");
const inputTelefono = document.getElementById("telefono-cliente");
const inputCorreo = document.getElementById("correo-cliente");

// Métodos de pago que exigen número de operación (Yape, Plin o voucher del POS).
const METODOS_CON_OPERACION = ['Yape', 'Plin', 'Tarjeta'];

// ── UMBRAL SUNAT: monto mínimo para emisión de comprobante electrónico ──
// Según normativa SUNAT (agosto 2026), los comprobantes electrónicos son
// obligatorios para ventas >= S/ 5.00. Por debajo de este monto, se emite
// una "Nota de Venta" (documento interno no válido fiscalmente).
const UMBRAL_COMPROBANTE = 5.00;

// Referencia al selector de tipo de comprobante y su aviso visual
const tipoComprobanteSelect = document.getElementById("tipo-comprobante-select");
const tipoComprobanteAviso = document.getElementById("tipo-comprobante-aviso");

let busquedaActiva = "";
let timeoutBusqueda = null;
let indiceActivoResultado = -1;
let resultadosActuales = [];

function limpiarResultados() {
  resultadosBusqueda.innerHTML = "";
  resultadosBusqueda.classList.add("hidden");
  indiceActivoResultado = -1;
  resultadosActuales = [];
}

function actualizarItemActivo() {
  const items = resultadosBusqueda.querySelectorAll(".search-result-item");

  items.forEach((item, index) => {
    const esActivo = index === indiceActivoResultado;
    item.classList.toggle("highlighted", esActivo);
    item.setAttribute("aria-selected", esActivo ? "true" : "false");
  });

  if (indiceActivoResultado >= 0 && items[indiceActivoResultado]) {
    items[indiceActivoResultado].scrollIntoView({ block: "nearest" });
  }
}

// ── Utilidades de presentaciones dinámicas ──────────────────────────────
// El stock SIEMPRE se mide en unidades mínimas (tableta, ml, unidad).
// Cada presentación define cuántas unidades base contiene (factor_conversion).

// Devuelve la presentación cuyo id coincide, o null si es venta por unidad.
function obtenerPresentacion(producto, presentacionId) {
  if (presentacionId == null || presentacionId === "") return null;
  const lista = Array.isArray(producto.presentaciones) ? producto.presentaciones : [];
  return lista.find((p) => Number(p.id) === Number(presentacionId)) || null;
}

// Factor de conversión de un item del carrito (unidades base por unidad vendida).
// La venta por 'Unidad' tiene factor implícito 1.
function factorDe(item) {
  return Math.max(Number(item && item.factor) || 1, 1);
}

// Etiqueta legible de la presentación de un item del carrito.
function etiquetaPresentacionDe(item) {
  return (item && item.presentacion_nombre) || "Unidad";
}

// Stock expresado en la presentación elegida: floor(stock_base / factor).
function stockEfectivoDe(stockBase, factor) {
  return Math.floor(Number(stockBase || 0) / factorDe({ factor }));
}

function renderizarResultados(resultados) {
  resultadosActuales = Array.isArray(resultados) ? resultados : [];

  if (resultadosActuales.length === 0) {
    resultadosBusqueda.innerHTML = `<div class="search-results empty">No se encontraron medicamentos.</div>`;
    resultadosBusqueda.classList.remove("hidden");
    return;
  }

  resultadosBusqueda.innerHTML = resultadosActuales
    .map((medicamento, index) => {
      const nombreEscapado = String(medicamento.nombre).replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const precioFormateado = Number(medicamento.precio).toFixed(2);
      const stock = medicamento.stock || medicamento.stock === 0 ? medicamento.stock : "-";
      const badgeReceta = medicamento.requiere_receta
        ? '<span class="receta-badge">⚠️ Requiere Receta</span>'
        : '';

      // Presentaciones dinámicas desde BD (además de la venta por Unidad implícita).
      const listaPres = Array.isArray(medicamento.presentaciones) ? medicamento.presentaciones : [];

      // Info de precios por presentación (incluye la unidad mínima).
      const infoPrecios = [
        `<div style="font-size:0.85rem;color:var(--muted);">Unidad: S/ ${precioFormateado}</div>`,
        ...listaPres.map((p) =>
          `<div style="font-size:0.82rem;color:var(--primary);font-weight:600;">${String(p.nombre).replace(/</g, "&lt;")}: S/ ${Number(p.precio).toFixed(2)} (${p.factor_conversion} uds)</div>`
        ),
      ].join("");

      // Un botón por cada forma de venta. data-pres-id="" = Unidad.
      const botonesAgregar = `
        <div style="display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end;">
          <button class="add-btn primary-btn" data-index="${index}" data-pres-id="" style="padding:6px 10px;min-height:32px;font-size:0.82rem;">Unidad</button>
          ${listaPres.map((p) =>
            `<button class="add-btn secondary-btn" data-index="${index}" data-pres-id="${p.id}" style="padding:6px 10px;min-height:32px;font-size:0.82rem;">${String(p.nombre).replace(/</g, "&lt;")}</button>`
          ).join("")}
        </div>`;

      return `
        <div class="search-result-item" role="option" data-index="${index}" tabindex="0">
          <div style="display:flex;flex-direction:column;gap:4px;">
            <div class="search-result-name">${nombreEscapado}</div>
            ${badgeReceta}
            <div style="font-size:0.85rem;color:var(--muted);">Stock: ${stock} unidades base</div>
          </div>
          <div style="display:flex;align-items:center;gap:10px;">
            <div style="text-align:right;">
              ${infoPrecios}
            </div>
            ${botonesAgregar}
          </div>
        </div>
      `;
    })
    .join("");

  resultadosBusqueda.classList.remove("hidden");
  indiceActivoResultado = -1;

  // Attach click listeners to add buttons
  const addButtons = resultadosBusqueda.querySelectorAll('.add-btn');
  addButtons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = Number(btn.dataset.index);
      const med = resultadosActuales[idx];
      if (med) {
        // data-pres-id="" (vacío) = venta por Unidad → se pasa null.
        const presId = btn.dataset.presId !== undefined && btn.dataset.presId !== ""
          ? Number(btn.dataset.presId)
          : null;
        agregarProductoAlCarrito(med.nombre, presId);
        limpiarResultados();
      }
    });
  });
}

function obtenerResultadosBusqueda(termino) {
  const busqueda = String(termino || "").trim().toLowerCase();

  if (busqueda.length === 0) {
    return productosSimulados.slice(0, 10); // Mostrar sugerencias iniciales cuando no hay texto.
  }

  return productosSimulados.filter((producto) => {
    const nombre = String(producto.nombre || "").toLowerCase();
    const componente = String(producto.componente || "").toLowerCase();
    const codigo = String(producto.codigo_barras || "").toLowerCase();
    return nombre.includes(busqueda) || componente.includes(busqueda) || codigo.includes(busqueda);
  });
}

function actualizarBusquedaEnVivo(termino) {
  busquedaActiva = termino;

  if (timeoutBusqueda) {
    clearTimeout(timeoutBusqueda);
  }

  timeoutBusqueda = setTimeout(() => {
    const resultados = obtenerResultadosBusqueda(busquedaActiva);
    renderizarResultados(resultados);
  }, 120);
}

function manejarClickResultado(event) {
  const item = event.target.closest(".search-result-item");
  if (!item) {
    return;
  }

  const index = Number(item.dataset.index);
  const medicamentoSeleccionado = resultadosActuales[index];

  if (!medicamentoSeleccionado) {
    return;
  }

  // Si se hizo click en un botón de presentación, usar ese formato de venta
  const tipoVentaBtn = event.target.closest('.add-btn');
  const presIdBtn = tipoVentaBtn && tipoVentaBtn.dataset.presId !== "" && tipoVentaBtn.dataset.presId !== undefined
    ? Number(tipoVentaBtn.dataset.presId)
    : null;

  agregarProductoAlCarrito(medicamentoSeleccionado.nombre, presIdBtn);
  buscadorMedicamentos.value = "";
  busquedaActiva = "";
  limpiarResultados();
}

function manejarTecladoBusqueda(event) {
  if (resultadosBusqueda.classList.contains("hidden")) {
    return;
  }

  switch (event.key) {
    case "ArrowDown": {
      event.preventDefault();
      if (resultadosActuales.length === 0) {
        return;
      }
      indiceActivoResultado = Math.min(indiceActivoResultado + 1, resultadosActuales.length - 1);
      actualizarItemActivo();
      break;
    }
    case "ArrowUp": {
      event.preventDefault();
      if (resultadosActuales.length === 0) {
        return;
      }
      indiceActivoResultado = Math.max(indiceActivoResultado - 1, 0);
      actualizarItemActivo();
      break;
    }
    case "Enter": {
      if (indiceActivoResultado < 0 || resultadosActuales.length === 0) {
        return;
      }
      event.preventDefault();
      const medicamentoSeleccionado = resultadosActuales[indiceActivoResultado];
      agregarProductoAlCarrito(medicamentoSeleccionado.nombre, null); // Enter = venta por unidad
      buscadorMedicamentos.value = "";
      busquedaActiva = "";
      limpiarResultados();
      break;
    }
    case "Escape": {
      limpiarResultados();
      break;
    }
    default:
      break;
  }
}

// Muestra información sobre el documento ingresado (DNI/RUC es opcional).
// Solo informativo: no bloquea ni muestra errores.
function validarDocumento() {
  const valor = inputDocumento.value.trim();
  const soloNumeros = valor.replace(/\D/g, "");

  if (soloNumeros.length === 8) {
    tipoComprobante.textContent = "DNI válido — se usará para Boleta si lo necesitas.";
    tipoComprobante.style.color = "#16a34a";
  } else if (soloNumeros.length === 11) {
    tipoComprobante.textContent = "RUC válido — se usará para Factura si lo necesitas.";
    tipoComprobante.style.color = "#16a34a";
  } else if (soloNumeros.length === 0) {
    tipoComprobante.textContent = "Si el cliente proporciona DNI/RUC, se autocompleta su nombre.";
    tipoComprobante.style.color = "var(--muted)";
  } else {
    tipoComprobante.textContent = `${soloNumeros.length} dígitos — ingresa 8 (DNI) o 11 (RUC) para buscar al cliente.`;
    tipoComprobante.style.color = "var(--muted)";
  }
}

// Búsqueda inteligente de clientes: consulta GET /api/cliente/<documento>.
// Si existe, autocompleta nombre y dirección; si no, los limpia.
let ultimaBusquedaCliente = 0;
async function buscarCliente() {
  const ahora = Date.now();
  if (ahora - ultimaBusquedaCliente < 600) return; // Evita doble disparo (blur + click)
  ultimaBusquedaCliente = ahora;

  const doc = inputDocumento.value.trim();
  const inputNombre = document.getElementById('cliente-nombre');
  const inputDireccion = document.getElementById('cliente-direccion');
  const soloNumeros = doc.replace(/\D/g, "");

  if (!soloNumeros) {
    showToast('warning', 'Ingresa un documento para buscar al cliente.');
    return;
  }
  if (soloNumeros.length !== 8 && soloNumeros.length !== 11) {
    showToast('warning', 'El documento debe tener 8 (DNI) o 11 (RUC) dígitos.');
    return;
  }

  try {
    const resp = await fetch(`/api/cliente/${encodeURIComponent(soloNumeros)}`);
    const data = await resp.json();

    if (resp.ok && data && data.success && data.cliente) {
      inputNombre.value = data.cliente.nombre || '';
      if (inputDireccion) inputDireccion.value = data.cliente.direccion || '';
      showToast('success', 'Cliente encontrado. Nombre y dirección completados.');
    } else if (resp.status === 404) {
      inputNombre.value = '';
      if (inputDireccion) inputDireccion.value = '';
      showToast('info', 'Cliente no registrado. Ingresa los datos manualmente.');
    } else {
      showToast('error', 'Error al buscar el cliente: ' + (data.error || resp.statusText));
    }
  } catch (err) {
    showToast('error', 'Error de red al buscar el cliente: ' + err.message);
  }

  try { if (typeof updateProcesarBtnState === 'function') updateProcesarBtnState(); } catch(e){}
}

// Calcula los totales a partir de la suma de los subtotales del carrito.
// Actualiza la Op. Gravada, el IGV y el Total a Pagar en pantalla.
function actualizarTotales() {
  const totalBruto = carrito.reduce((acumulador, item) => acumulador + item.subtotal, 0); // Suma todos los subtotales.
  const operacionGravada = totalBruto / 1.18; // Dividir entre 1.18 según matemática SUNAT.
  const igv = totalBruto - operacionGravada; // IGV es la diferencia entre total y operación gravada.

  opGravadaElemento.textContent = `S/ ${operacionGravada.toFixed(2)}`; // Mostrar con 2 decimales.
  igvElemento.textContent = `S/ ${igv.toFixed(2)}`; // Mostrar IGV con 2 decimales.
  totalPagarElemento.textContent = `S/ ${totalBruto.toFixed(2)}`; // Mostrar total bruto con 2 decimales.
}

// Redibuja el contenido de la tabla del carrito en el HTML cada vez que cambia el carrito.
function actualizarTablaCarrito() {
  // ── Actualizar encabezado de columna Precio según presentaciones en carrito ──
  const thPrecio = document.getElementById('th-precio');
  if (thPrecio) {
    const hayPresentacion = carrito.some(item => factorDe(item) > 1);
    const hayUnidad = carrito.some(item => factorDe(item) === 1);
    if (hayPresentacion && hayUnidad) {
      thPrecio.textContent = 'Precio / Ud·Pres.';
    } else if (hayPresentacion) {
      thPrecio.textContent = 'Precio / Presentación';
    } else {
      thPrecio.textContent = 'Precio Unit.';
    }
  }

  if (carrito.length === 0) {
    carritoBody.innerHTML = `
      <tr>
        <td colspan="6" style="padding: 20px 16px; text-align: center; color: var(--muted);">El carrito está vacío. Agrega un medicamento para comenzar.</td>
      </tr>
    `; // Mensaje cuando el carrito está vacío.
    actualizarTotales(); // Aun cuando está vacío, actualizar totales a cero.
    return;
  }

  carritoBody.innerHTML = ""; // Limpiar la tabla antes de repoblarla.

  carrito.forEach((item, index) => {
    const fila = document.createElement("tr"); // Crear una fila para cada producto.

    // Encontrar el stock en la lista de productos (actualizada desde backend)
    const productoInfo = productosSimulados.find(p => String(p.nombre).toLowerCase() === String(item.nombre).toLowerCase()) || {};
    const stockDisponible = Number(productoInfo.stock || item.stock || 0);
    const factor = factorDe(item);                       // unidades base por presentación
    const nombrePres = etiquetaPresentacionDe(item);     // 'Caja', 'Blíster', 'Unidad'...
    const esUnidad = factor === 1;
    const stockEfectivo = Math.floor(stockDisponible / factor);
    // Etiqueta de stock en el idioma del cajero: cuántas presentaciones caben
    // con el stock base actual, y cuántas unidades base quedan.
    const etiquetaStock = esUnidad
      ? `Stock disponible: ${stockDisponible}`
      : `Stock: ${stockEfectivo} × ${nombrePres} (${stockDisponible} uds base)`;
    const labelTipo = nombrePres;

    fila.innerHTML = `
      <td>
        <div class="product-name">${item.nombre}</div>
        <div style="font-size:0.82rem;color:var(--primary);font-weight:600;margin-top:4px;">${labelTipo}</div>
      </td>
      <td class="quantity">
        <div class="qty-controls">
          <button type="button" class="qty-decrease" data-index="${index}" aria-label="Disminuir cantidad">-</button>
          <input type="number" class="qty-input" data-index="${index}" min="1" max="${stockEfectivo}" value="${item.cantidad}" style="width:64px; text-align:center;" />
          <button type="button" class="qty-increase" data-index="${index}" aria-label="Aumentar cantidad">+</button>
        </div>
        <div class="stock-info" style="font-size:0.85rem;color:var(--muted);margin-top:6px;">${etiquetaStock}</div>
        <div class="stock-warning" style="color:#b91c1c; font-size:0.85rem; margin-top:6px; display:none;"></div>
      </td>
      <td class="receta-cell">
        ${item.requiere_receta ? `
          <div class="receta-control">
            <span class="receta-badge">⚠️ Requiere Receta</span>
            <label class="receta-checkbox">
              <input type="checkbox" class="receta-toggle" data-index="${index}" ${item.tiene_receta ? 'checked' : ''} aria-label="¿El cliente cuenta con receta médica para ${item.nombre}?" />
              ¿Cuenta con receta?
            </label>
          </div>
        ` : '<span class="receta-na">No aplica</span>'}
      </td>
      <td class="price" title="Precio por ${nombrePres.toLowerCase()}${esUnidad ? '' : ` (${factor} uds base)`}">
        S/ ${item.precio.toFixed(2)}
        ${esUnidad
          ? '<span style="display:block;font-size:0.72rem;color:var(--muted);">/unidad</span>'
          : `<span style="display:block;font-size:0.72rem;color:var(--primary);font-weight:600;">/${nombrePres.toLowerCase()}</span>`}
      </td>
      <td class="subtotal">S/ ${item.subtotal.toFixed(2)}</td>
      <td class="eliminar-cell">
        <button type="button" class="remove-btn" data-index="${index}" aria-label="Eliminar producto">×</button>
      </td>
    `; // Crear los campos de producto, cantidad, precio y subtotal.

    carritoBody.appendChild(fila); // Agregar la fila al cuerpo de la tabla.
  });

  // Agregar eventos a los botones de eliminar luego de crear la tabla.
  const botonesEliminar = carritoBody.querySelectorAll(".remove-btn");
  botonesEliminar.forEach((boton) => {
    boton.addEventListener("click", () => {
      const indice = Number(boton.dataset.index); // Obtener el índice del producto a eliminar.
      carrito.splice(indice, 1); // Eliminar el producto del carrito.
      actualizarTablaCarrito(); // Redibujar la tabla después de eliminar.
    });
  });

  // Agregar eventos a controles de cantidad
  const botonesAumentar = carritoBody.querySelectorAll(".qty-increase");
  botonesAumentar.forEach((boton) => {
    boton.addEventListener("click", () => {
      const indice = Number(boton.dataset.index);
      if (carrito[indice]) {
        const productoInfo = productosSimulados.find(p => String(p.nombre).toLowerCase() === String(carrito[indice].nombre).toLowerCase()) || {};
        const stockDisponible = Number(productoInfo.stock || carrito[indice].stock || 0);
        const factor = factorDe(carrito[indice]);
        const nombrePres = etiquetaPresentacionDe(carrito[indice]);
        const stockEfectivo = Math.floor(stockDisponible / factor);
        if (carrito[indice].cantidad < stockEfectivo) {
          carrito[indice].cantidad += 1;
          carrito[indice].subtotal = carrito[indice].precio * carrito[indice].cantidad;
        } else {
          const row = boton.closest('tr');
          const warn = row.querySelector('.stock-warning');
          if (warn) {
            warn.textContent = `Stock máximo alcanzado (${stockEfectivo} × ${nombrePres})`;
            warn.style.display = 'block';
            setTimeout(() => { warn.style.display = 'none'; }, 2500);
          }
        }
        actualizarTablaCarrito();
      }
    });
  });

  const botonesDisminuir = carritoBody.querySelectorAll(".qty-decrease");
  botonesDisminuir.forEach((boton) => {
    boton.addEventListener("click", () => {
      const indice = Number(boton.dataset.index);
      if (carrito[indice]) {
        if (carrito[indice].cantidad > 1) {
          carrito[indice].cantidad -= 1;
          carrito[indice].subtotal = carrito[indice].precio * carrito[indice].cantidad;
        } else {
          carrito.splice(indice, 1);
        }
        actualizarTablaCarrito();
      }
    });
  });

  // Input editable: validar cambios manuales
  const inputsQty = carritoBody.querySelectorAll('.qty-input');
  inputsQty.forEach(input => {
    input.addEventListener('change', (e) => {
      const idx = Number(input.dataset.index);
      let val = Number(input.value) || 1;
      if (!carrito[idx]) return;

      const productoInfo = productosSimulados.find(p => String(p.nombre).toLowerCase() === String(carrito[idx].nombre).toLowerCase()) || {};
      const stockDisponible = Number(productoInfo.stock || carrito[idx].stock || 0);
      const factor = factorDe(carrito[idx]);
      const nombrePres = etiquetaPresentacionDe(carrito[idx]);
      const stockEfectivo = Math.floor(stockDisponible / factor);

      if (val < 1) val = 1;
      if (val > stockEfectivo) {
        val = stockEfectivo;
        const row = input.closest('tr');
        const warn = row.querySelector('.stock-warning');
        if (warn) {
          warn.textContent = `Stock máximo: ${stockEfectivo} × ${nombrePres}`;
          warn.style.display = 'block';
          setTimeout(() => { warn.style.display = 'none'; }, 2500);
        }
      }

      if (val === 0) {
        carrito.splice(idx, 1);
      } else {
        carrito[idx].cantidad = val;
        carrito[idx].subtotal = carrito[idx].precio * carrito[idx].cantidad;
      }
      actualizarTablaCarrito();
    });
  });

  // Receta médica por ítem: guardar la respuesta del cliente sin re-renderizar
  const togglesReceta = carritoBody.querySelectorAll('.receta-toggle');
  togglesReceta.forEach((toggle) => {
    toggle.addEventListener('change', (e) => {
      const indice = Number(toggle.dataset.index);
      if (carrito[indice]) {
        carrito[indice].tiene_receta = toggle.checked;
      }
    });
  });

  actualizarTotales(); // Actualizar los totales cada vez que cambie el carrito.

  // ── Selector inteligente de tipo de comprobante ──
  // Cuando el carrito cambia, re-evaluar si corresponde Nota de Venta o Boleta.
  // Resetear la bandera de "forzado" para que la auto-selección vuelva a actuar.
  tipoComprobanteForzado = false;
  evaluarTipoComprobante();

  // Actualizar estado del botón procesar venta (si existe)
  try { if (typeof updateProcesarBtnState === 'function') updateProcesarBtnState(); } catch(e){}
}

// Agrega un medicamento al carrito con la cantidad indicada, sumando cantidades si ya existe.
// presentacion_id = null → venta por Unidad (factor 1).
// El precio y el factor vienen de las presentaciones cargadas desde la BD
// (el backend los revalida al procesar la venta: nunca se confía en el frontend).
function agregarProductoAlCarrito(nombre, presentacion_id = null) {
  // Obtener información completa del producto desde la fuente autoritativa
  const productoInfo = productosSimulados.find(p => String(p.nombre).toLowerCase() === String(nombre).toLowerCase()) || {};
  const stockDisponible = Number(productoInfo.stock || 0);

  // ── Resolver presentación elegida (o unidad mínima por defecto) ──
  const pres = obtenerPresentacion(productoInfo, presentacion_id);
  if (presentacion_id != null && !pres) {
    showToast('warning', `Presentación no disponible para ${nombre}. Se agrega por unidad.`);
  }

  const precio = pres ? Number(pres.precio) : Number(productoInfo.precio || 0);
  const factor = pres ? Math.max(Number(pres.factor_conversion) || 1, 1) : 1;
  const nombrePres = pres ? pres.nombre : "Unidad";

  // Stock efectivo en la presentación elegida: floor(stock_base / factor)
  // ej: stock 45 tabletas, Caja=30 → se pueden vender 1 caja.
  const stockEfectivo = Math.floor(stockDisponible / factor);

  // Buscar si ya existe el mismo producto con la misma presentación en el carrito
  const productoExistente = carrito.find(
    (item) => String(item.nombre).toLowerCase() === String(nombre).toLowerCase() &&
              (item.presentacion_id ?? null) === (presentacion_id ?? null)
  );

  if (productoExistente) {
    if (productoExistente.cantidad + 1 > stockEfectivo) {
      showToast('warning', `Stock máximo alcanzado para ${nombre} (${nombrePres}): ${stockEfectivo}`);
      return;
    }
    productoExistente.cantidad += 1;
    productoExistente.subtotal = precio * productoExistente.cantidad;
  } else {
    if (stockEfectivo < 1) {
      showToast('warning', `Stock insuficiente para ${nombre} (${nombrePres}): requiere ${factor} uds base`);
      return;
    }
    const nuevoProducto = {
      nombre,
      precio,
      cantidad: 1,
      subtotal: precio * 1,
      stock: stockDisponible,
      id: productoInfo.id || null,
      requiere_receta: Boolean(productoInfo.requiere_receta),
      tiene_receta: false,
      // Datos de la presentación vendida (el backend revalida contra BD)
      presentacion_id: pres ? Number(pres.id) : null,
      presentacion_nombre: nombrePres,
      factor,
    };
    carrito.push(nuevoProducto);
  }

  // Feedback visual: mostrar qué precio se aplicó
  showToast('success', `${nombre} (${nombrePres}) agregado — S/ ${precio.toFixed(2)}`);

  actualizarTablaCarrito();
}

function inicializarBuscador() {
  if (!buscadorMedicamentos || !resultadosBusqueda) {
    return;
  }

  buscadorMedicamentos.addEventListener("input", (event) => {
    actualizarBusquedaEnVivo(event.target.value);
  });

  buscadorMedicamentos.addEventListener("focus", (event) => {
    const resultados = obtenerResultadosBusqueda(event.target.value);
    renderizarResultados(resultados);
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".buscador-group")) {
      limpiarResultados();
    }
  });

  resultadosBusqueda.addEventListener("click", manejarClickResultado);
}

// =========================================================
// SOPORTE PISTOLA LECTORA / CÓDIGO DE BARRAS
// =========================================================
// La pistola se comporta como un teclado: escribe el código muy rápido
// y finaliza con Enter (o Tab). El input dedicado siempre tiene el foco,
// por lo que el escaneo agrega el producto al carrito al instante.

function enfocarCodigoBarras() {
  if (inputCodigoBarras && document.activeElement !== inputCodigoBarras) {
    inputCodigoBarras.focus();
    inputCodigoBarras.select();
  }
}

function procesarCodigoBarras() {
  if (!inputCodigoBarras) return;

  const codigo = String(inputCodigoBarras.value || "").trim();
  inputCodigoBarras.value = "";

  if (!codigo) {
    enfocarCodigoBarras();
    return;
  }

  // Buscar el producto por código de barras exacto en la lista del backend.
  const producto = productosSimulados.find(
    (p) => p.codigo_barras != null && String(p.codigo_barras).trim() === codigo
  );

  if (!producto) {
    showToast('error', `Código ${codigo} no encontrado en inventario`);
    enfocarCodigoBarras();
    return;
  }

  const stock = Number(producto.stock || 0);
  if (stock <= 0) {
    showToast('warning', `Sin stock: ${producto.nombre}`);
    enfocarCodigoBarras();
    return;
  }

  agregarProductoAlCarrito(producto.nombre, null); // escaneo = venta por unidad
  showToast('success', `${producto.nombre} agregado al carrito`);
  enfocarCodigoBarras();
}

function inicializarCodigoBarras() {
  if (!inputCodigoBarras) return;

  // Enter (o Tab, según configuración de la pistola) = fin del escaneo.
  inputCodigoBarras.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      procesarCodigoBarras();
    }
  });

  // Click = seleccionar todo para el siguiente escaneo.
  inputCodigoBarras.addEventListener("click", () => inputCodigoBarras.select());

  // Si el foco está fuera de un campo de texto y se teclea algo,
  // redirigirlo al campo de código de barras (la pistola funciona desde cualquier parte).
  document.addEventListener("keydown", (event) => {
    if (!event || !event.key || event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    const elementoActivo = document.activeElement;
    const enCampo = elementoActivo && (
      elementoActivo.tagName === "INPUT" ||
      elementoActivo.tagName === "TEXTAREA" ||
      elementoActivo.tagName === "SELECT" ||
      elementoActivo.isContentEditable
    );
    if (!enCampo) {
      inputCodigoBarras.focus();
    }
  });

  enfocarCodigoBarras();
}

async function askRecetaConfirmacion() {
  return new Promise((resolve) => {
    const modal = document.getElementById('receta-modal');
    const btnSi = document.getElementById('receta-modal-si');
    const btnNo = document.getElementById('receta-modal-no');

    if (!modal || !btnSi || !btnNo) {
      resolve(false);
      return;
    }

    function cerrar(respuesta) {
      modal.classList.add('hidden');
      modal.setAttribute('aria-hidden', 'true');
      btnSi.removeEventListener('click', onSi);
      btnNo.removeEventListener('click', onNo);
      resolve(respuesta);
    }

    function onSi() {
      cerrar(true);
    }

    function onNo() {
      cerrar(false);
    }

    btnSi.addEventListener('click', onSi);
    btnNo.addEventListener('click', onNo);
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    btnNo.focus();
  });
}

// Muestra u oculta los paneles dinámicos y campos según el método de pago elegido.
function actualizarPanelPago() {
  const metodo = (medioPagoEl && medioPagoEl.value) || '';
  const esYape = metodo === 'Yape';
  const esPlin = metodo === 'Plin';
  const esTarjeta = metodo === 'Tarjeta';
  const esEfectivo = metodo === 'Efectivo';

  if (panelYape) panelYape.classList.toggle('hidden', !esYape);
  if (panelPlin) panelPlin.classList.toggle('hidden', !esPlin);
  if (panelTarjeta) panelTarjeta.classList.toggle('hidden', !esTarjeta);

  // Número de operación: visible y obligatorio solo para Yape, Plin y Tarjeta.
  const requiereOperacion = METODOS_CON_OPERACION.includes(metodo);
  if (grupoNumeroOperacion) grupoNumeroOperacion.classList.toggle('hidden', !requiereOperacion);
  if (inputNumeroOperacion) {
    inputNumeroOperacion.required = requiereOperacion;
    if (!requiereOperacion) inputNumeroOperacion.value = '';
  }

  // Monto recibido (vuelto) solo tiene sentido en efectivo.
  if (grupoMontoPagado) grupoMontoPagado.classList.toggle('hidden', !esEfectivo);

  try { if (typeof updateProcesarBtnState === 'function') updateProcesarBtnState(); } catch(e){}
}

// Muestra u oculta los campos de contacto cuando el comprobante es digital.
function actualizarPanelContacto() {
  const esDigital = tipoEnvioEl && tipoEnvioEl.value === 'DIGITAL';
  if (grupoContactoDigital) grupoContactoDigital.classList.toggle('hidden', !esDigital);

  try { if (typeof updateProcesarBtnState === 'function') updateProcesarBtnState(); } catch(e){}
}

// =========================================================
// SELECTOR INTELIGENTE DE TIPO DE DOCUMENTO (S/ 5.00)
// =========================================================
// REGLA ABSOLUTA: el total manda sobre cualquier otra cosa.
//
//   total < S/ 5.00  →  NOTA_VENTA (siempre, sin excepción)
//   total >= S/ 5.00 →  BOLETA (doc 8 dígitos) o FACTURA (11 dígitos)
//
// Si el cajero forzó manualmente Boleta/Factura y luego el total
// baja de S/ 5.00, se SOBREESCRIBE a Nota de Venta automáticamente.
// El DNI/RUC en el campo de texto NUNCA influye en esta decisión.
//
// Se llama desde actualizarTablaCarrito() cada vez que cambia el carrito.
function evaluarTipoComprobante() {
  if (!tipoComprobanteSelect || !tipoComprobanteAviso) return;

  const totalVenta = carrito.reduce((s, it) => s + it.subtotal, 0);
  const debajoUmbral = totalVenta < UMBRAL_COMPROBANTE;

  // ── PRIORIDAD 1: Si el cajero forzó manualmente, SIEMPRE respetar ──
  // Aunque el total sea menor a S/ 5.00, si eligió Boleta o Factura,
  // se respeta su decisión (el cliente puede necesitarlo para seguro/empresa).
  if (!tipoComprobanteForzado) {
    // ── PRIORIDAD 2: Auto-selección según el total ──
    if (debajoUmbral) {
      tipoComprobanteSelect.value = 'NOTA_VENTA';
    } else {
      const doc = (inputDocumento && inputDocumento.value || '').replace(/\D/g, '');
      tipoComprobanteSelect.value = doc.length === 11 ? 'FACTURA' : 'BOLETA';
    }
  }

  // ── Aviso visual ──
  const seleccionado = tipoComprobanteSelect.value;

  if (seleccionado === 'NOTA_VENTA' && !debajoUmbral) {
    tipoComprobanteAviso.textContent = `Sugerencia: Esta venta supera los S/ ${UMBRAL_COMPROBANTE.toFixed(2)}, se recomienda emitir Boleta Electrónica.`;
    tipoComprobanteAviso.className = 'tipo-comprobante-aviso';
  } else if (seleccionado === 'NOTA_VENTA' && debajoUmbral) {
    tipoComprobanteAviso.textContent = `Documento interno (venta menor a S/ ${UMBRAL_COMPROBANTE.toFixed(2)}).`;
    tipoComprobanteAviso.className = 'tipo-comprobante-aviso';
  } else if (seleccionado === 'FACTURA') {
    tipoComprobanteAviso.textContent = 'Factura Electrónica — requiere RUC (11 dígitos).';
    tipoComprobanteAviso.className = 'tipo-comprobante-aviso';
  } else {
    tipoComprobanteAviso.textContent = 'Boleta Electrónica — documento válido ante SUNAT.';
    tipoComprobanteAviso.className = 'tipo-comprobante-aviso';
  }

  try { if (typeof updateProcesarBtnState === 'function') updateProcesarBtnState(); } catch(e){}
}

// Bandera: true cuando el cajero cambia manualmente el selector.
// Se resetea a false cuando el carrito cambia (para reactivar auto-selección).
let tipoComprobanteForzado = false;

function configurarSelectorComprobante() {
  if (!tipoComprobanteSelect) return;

  tipoComprobanteSelect.addEventListener('change', () => {
    // Marcar como forzado: el cajero tomó una decisión manual
    tipoComprobanteForzado = true;

    // Re-evaluar el aviso visual según la nueva selección
    evaluarTipoComprobante();
  });
}

// Genera un enlace wa.me/ con el resumen del comprobante listo para enviar.
function generarEnlaceWhatsApp(numero, tipoComp, serie, correlativo, nombreCliente, carritoItems, total, metodoPago) {
  const numLimpio = String(numero).replace(/\D/g, '');
  const fecha = new Date().toLocaleDateString('es-PE', { day: '2-digit', month: '2-digit', year: 'numeric' });
  const hora = new Date().toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' });

  const lineas = [];
  lineas.push(`🧾 *${tipoComp} ${serie}-${String(correlativo).padStart(6, '0')}*`);
  lineas.push(`📅 ${fecha} ${hora}`);
  lineas.push('');
  lineas.push(`👤 *Cliente:* ${nombreCliente}`);
  lineas.push('');
  lineas.push('*Detalle:*');
  carritoItems.forEach(it => {
    lineas.push(`  • ${it.nombre} x${it.cantidad} — S/ ${it.subtotal.toFixed(2)}`);
  });
  lineas.push('');
  lineas.push(`💰 *Total: S/ ${total.toFixed(2)}*`);
  lineas.push(`💳 Pago: ${metodoPago}`);
  lineas.push('');
  lineas.push('¡Gracias por su compra! 🙏');

  const texto = encodeURIComponent(lineas.join('\n'));
  return `https://wa.me/51${numLimpio}?text=${texto}`;
}

// Procesar venta: recopila carrito, cliente y totales y envía POST a /api/ventas
async function procesarVenta() {
  if (carrito.length === 0) {
    showToast('warning', 'El carrito está vacío. Agrega productos antes de procesar la venta.');
    return;
  }

  if (isProcessingVenta) {
    showToast('warning', 'La venta ya se está procesando, espera...');
    return;
  }

  const documento = (document.getElementById('cliente-documento').value || '').trim();
  const nombreCliente = (document.getElementById('cliente-nombre').value || '').trim();
  const direccionCliente = (document.getElementById('cliente-direccion').value || '').trim();
  const metodoPago = (medioPagoEl && medioPagoEl.value) || '';
  const numeroOperacion = (inputNumeroOperacion && inputNumeroOperacion.value.trim()) || '';
  const montoPagado = (inputMontoPagado && inputMontoPagado.value.trim()) || '';
  const tipoEnvio = (tipoEnvioEl && tipoEnvioEl.value) || 'FISICO';
  const telefonoCliente = (inputTelefono && inputTelefono.value.trim()) || '';
  const correoCliente = (inputCorreo && inputCorreo.value.trim()) || '';

  if (!nombreCliente) {
    showToast('warning', 'Ingresa el nombre del cliente para procesar la venta.');
    return;
  }

  if (!metodoPago) {
    showToast('warning', 'Selecciona el método de pago antes de procesar la venta.');
    return;
  }

  // El comprobante digital exige número de WhatsApp (correo es opcional).
  if (tipoEnvio === 'DIGITAL' && !telefonoCliente) {
    showToast('warning', 'Para el comprobante digital ingresa el número de WhatsApp del cliente.');
    if (inputTelefono) inputTelefono.focus();
    return;
  }

  // Yape, Plin y Tarjeta exigen el número de operación / voucher.
  if (METODOS_CON_OPERACION.includes(metodoPago) && !numeroOperacion) {
    const etiqueta = { Yape: 'Yape', Plin: 'Plin', Tarjeta: 'voucher del POS' }[metodoPago] || 'operación';
    showToast('warning', `Ingresa el número de operación del ${etiqueta} antes de procesar la venta.`);
    if (inputNumeroOperacion) inputNumeroOperacion.focus();
    return;
  }

  // Validar monto recibido SOLO si el cajero lo ingresó (campo es opcional).
  const totalVenta = carrito.reduce((s, it) => s + it.subtotal, 0);
  const montoPagadoNum = montoPagado ? Number(montoPagado) : null;
  if (metodoPago === 'Efectivo' && montoPagadoNum !== null && !Number.isNaN(montoPagadoNum)) {
    if (montoPagadoNum < totalVenta) {
      showToast('warning', `El monto recibido (S/ ${montoPagadoNum.toFixed(2)}) es menor al total (S/ ${totalVenta.toFixed(2)}).`);
      if (inputMontoPagado) inputMontoPagado.focus();
      return;
    }
  }

  // Leer el tipo de documento DIRECTAMENTE del selector.
  // No hay ninguna función que sobrescriba este valor al clickear "Cobrar".
  // El selector es la única fuente de verdad.
  const tipoComp = (tipoComprobanteSelect && tipoComprobanteSelect.value) || 'NOTA_VENTA';

  // construir carrito para backend
  // El frontend SOLO envía el id de la presentación elegida (o null = unidad).
  // Precio y factor los decide el backend desde la BD (blindaje anti-manipulación).
  const carritoPayload = carrito.map(item => ({
    nombre: item.nombre,
    cantidad: item.cantidad,
    presentacion_id: item.presentacion_id ?? null,
    requiere_receta: Boolean(item.requiere_receta),
    tiene_receta: Boolean(item.tiene_receta),
  }));

  const total = carrito.reduce((s, it) => s + it.subtotal, 0);
  const totalFixed = Number(total.toFixed(2));
  const subtotalCalc = Number((totalFixed / 1.18).toFixed(2));
  const igvCalc = Number((totalFixed - subtotalCalc).toFixed(2));

  // Confirmar receta para los ítems que la requieren y aún no la han confirmado en el carrito
  const itemsRecetaSinConfirmar = carrito.filter(item => item.requiere_receta && !item.tiene_receta);
  if (itemsRecetaSinConfirmar.length > 0) {
    const confirmacion = await askRecetaConfirmacion();
    if (confirmacion) {
      itemsRecetaSinConfirmar.forEach(item => { item.tiene_receta = true; });
    } else {
      showToast('warning', 'Venta cancelada. Marca la receta en el carrito para: ' +
        itemsRecetaSinConfirmar.map(i => i.nombre).join(', '));
      return;
    }
  }

  const tiene_receta = carrito.some(item => item.requiere_receta && item.tiene_receta);

  const payload = {
    tipo_comprobante: tipoComp,
    cliente: { documento, nombre: nombreCliente, direccion: direccionCliente },
    carrito: carritoPayload,
    metodo_pago: metodoPago,
    monto_pagado: metodoPago === 'Efectivo' && montoPagado ? Number(montoPagado) : null,
    numero_operacion: numeroOperacion || null,
    tipo_envio_comprobante: tipoEnvio,
    telefono_cliente: telefonoCliente || null,
    correo_cliente: correoCliente || null,
    totales: { subtotal: subtotalCalc, igv: igvCalc, total: totalFixed },
    tiene_receta: tiene_receta
  };

  // Marcar como procesando y bloquear UI
  isProcessingVenta = true;
  const btnProcesar = document.getElementById('procesar-venta-btn');
  let prevText = null;
  if (btnProcesar) {
    const textEl = btnProcesar.querySelector('.btn-text');
    const spinnerEl = btnProcesar.querySelector('.btn-spinner');
    prevText = textEl ? textEl.textContent : btnProcesar.textContent;
    if (textEl) textEl.textContent = 'Procesando...';
    if (spinnerEl) spinnerEl.classList.remove('hidden');
    btnProcesar.disabled = true;
    btnProcesar.classList.add('processing');
    btnProcesar.setAttribute('aria-busy', 'true');
  }

  try {
    const resp = await fetch('/api/ventas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await resp.json();
    if (resp.status === 201 && data && data.success) {
      // Feedback inmediato al cajero con el número del comprobante
      const numeroComprobante = data.correlativo != null
        ? `${data.serie || ''}-${String(data.correlativo).padStart(6, '0')}`
        : '';
      showToast('success', `¡Venta registrada con éxito! (${tipoComp} N° ${numeroComprobante})`);

      // Si es comprobante digital, mostrar botón de envío por WhatsApp
      if (tipoEnvio === 'DIGITAL' && telefonoCliente) {
        const totalVenta = carrito.reduce((s, it) => s + it.subtotal, 0);
        const enlaceWA = generarEnlaceWhatsApp(
          telefonoCliente, tipoComp, data.serie, data.correlativo,
          nombreCliente, carrito, totalVenta, metodoPago
        );
        mostrarBotonWhatsApp(enlaceWA, numeroComprobante);
      }

      // actualizar stock local en productosSimulados
      // Se descuentan las unidades BASE reales: cantidad × factor de conversión.
      carrito.forEach(it => {
        const p = productosSimulados.find(p => String(p.nombre).toLowerCase() === String(it.nombre).toLowerCase());
        if (p) {
          const unidadesADescontar = it.cantidad * factorDe(it);
          p.stock = Math.max(0, Number(p.stock || 0) - unidadesADescontar);
        }
      });

      // 1) limpiar el carrito y redibujar la tabla
      carrito.length = 0;
      actualizarTablaCarrito();

      // 2) reiniciar el formulario de pago (método, montos, operación, contacto)
      if (medioPagoEl) medioPagoEl.value = '';
      if (inputMontoPagado) inputMontoPagado.value = '';
      if (inputNumeroOperacion) inputNumeroOperacion.value = '';
      if (tipoEnvioEl) tipoEnvioEl.value = 'FISICO';
      if (inputTelefono) inputTelefono.value = '';
      if (inputCorreo) inputCorreo.value = '';
      const avisoMonto = document.getElementById('monto-aviso');
      if (avisoMonto) {
        avisoMonto.textContent = '';
        avisoMonto.className = '';
      }
      actualizarPanelPago();
      actualizarPanelContacto();

      // limpiar campos cliente
      document.getElementById('cliente-nombre').value = '';
      document.getElementById('cliente-documento').value = '';
      const inputDireccion = document.getElementById('cliente-direccion');
      if (inputDireccion) inputDireccion.value = '';
      tipoComprobante.textContent = 'Si el cliente proporciona DNI/RUC, se autocompleta su nombre.';

      // 3) recargar la lista de medicamentos desde el backend para que
      //    el stock actualizado se refleje en la tabla y en las búsquedas
      await cargarMedicamentosDesdeBackend();
      actualizarTablaCarrito();

      // Re-evaluar el estado del botón procesar y reenfocar la pistola lectora
      try { if (typeof updateProcesarBtnState === 'function') updateProcesarBtnState(); } catch(e){}
      enfocarCodigoBarras();
    } else {
      showToast('error', `Error procesando la venta: ${data.error || resp.statusText}`);
    }
  } catch (err) {
    showToast('error', 'Error de red al procesar la venta: ' + err.message);
  } finally {
    // Restaurar estado del botón y flag
    isProcessingVenta = false;
    if (btnProcesar) {
      const textEl = btnProcesar.querySelector('.btn-text');
      const spinnerEl = btnProcesar.querySelector('.btn-spinner');
      if (textEl) textEl.textContent = prevText || 'Procesar Venta';
      if (spinnerEl) spinnerEl.classList.add('hidden');
      btnProcesar.classList.remove('processing');
      btnProcesar.removeAttribute('aria-busy');
      btnProcesar.disabled = false;
    }
    // Re-evaluar si el botón debe estar habilitado según campos y carrito
    try { if (typeof updateProcesarBtnState === 'function') updateProcesarBtnState(); } catch(e){}
  }
}

// Inicializar la lógica cuando el DOM haya cargado por completo.
document.addEventListener("DOMContentLoaded", async () => {
  inputDocumento.addEventListener("input", validarDocumento); // Validar documento cada vez que el usuario escribe.

  // Búsqueda inteligente de cliente: al salir del campo, con Enter o con el botón "Buscar"
  const btnBuscarCliente = document.getElementById('buscar-cliente-btn');
  inputDocumento.addEventListener('blur', () => {
    const doc = inputDocumento.value.replace(/\D/g, "");
    if (doc.length === 8 || doc.length === 11) buscarCliente();
  });
  inputDocumento.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      buscarCliente();
    }
  });
  if (btnBuscarCliente) btnBuscarCliente.addEventListener('click', buscarCliente);

  // Aquí es donde se debe ejecutar el fetch para cargar la lista real de medicamentos
  // desde el backend Python antes de inicializar el buscador.
  await cargarMedicamentosDesdeBackend();

  // Registrar evento del botón de procesar venta
  const btnProcesar = document.getElementById('procesar-venta-btn');
  if (btnProcesar) btnProcesar.addEventListener('click', procesarVenta);

  // Disable/enable procesar button based on required fields
  function updateProcesarBtnState() {
    const documentoVal = (document.getElementById('cliente-documento').value || '').trim();
    const nombreVal = (document.getElementById('cliente-nombre').value || '').trim();
    const medioVal = (medioPagoEl && medioPagoEl.value) || '';
    const numOpVal = (inputNumeroOperacion && inputNumeroOperacion.value.trim()) || '';
    const requiereNumOp = METODOS_CON_OPERACION.includes(medioVal);
    const pagoOk = !requiereNumOp || numOpVal.length > 0;
    const tipoEnvioVal = (tipoEnvioEl && tipoEnvioEl.value) || 'FISICO';
    const contactoOk = tipoEnvioVal !== 'DIGITAL' ||
      Boolean(inputTelefono && inputTelefono.value.trim());

    // Monto recibido (efectivo): siempre es opcional.
    // Si el cajero lo deja en blanco, se asume pago exacto (el backend guarda el total).
    // Solo se valida que, si se ingresa un monto, no sea menor al total.
    const esEfectivo = medioVal === 'Efectivo';
    const totalPagar = carrito.reduce((acc, item) => acc + (Number(item.subtotal) || 0), 0);
    const montoVal = (inputMontoPagado && String(inputMontoPagado.value || '').trim()) || '';
    const montoNum = Number(montoVal);
    const montoCentavos = Math.round(montoNum * 100);
    const totalCentavos = Math.round(totalPagar * 100);
    const montoIngresado = esEfectivo && montoVal.length > 0 && !Number.isNaN(montoNum);
    const montoValido = montoIngresado && montoCentavos >= totalCentavos;
    const montoOk = true; // Siempre OK: campo es opcional

    // Feedback visual del monto recibido (vuelto o lo que falta).
    const avisoMonto = document.getElementById('monto-aviso');
    if (avisoMonto) {
      if (!esEfectivo || montoVal.length === 0) {
        // Sin monto ingresado o no es efectivo: limpiar aviso
        avisoMonto.textContent = esEfectivo ? 'Pago exacto (deja vacío para pago exacto)' : '';
        avisoMonto.className = esEfectivo ? 'monto-ok' : '';
      } else if (montoValido) {
        const vuelto = ((montoCentavos - totalCentavos) / 100).toFixed(2);
        avisoMonto.textContent = `Vuelto: S/ ${vuelto}`;
        avisoMonto.className = 'monto-ok';
      } else {
        const falta = Math.max(totalCentavos - montoCentavos, 0) / 100;
        avisoMonto.textContent = `Falta S/ ${falta.toFixed(2)}`;
        avisoMonto.className = 'monto-error';
      }
    }

    // ====== Depuración: cada condición por separado ======
    const condCarrito = carrito.length > 0;
    const condDocumento = documentoVal.length > 0; // informativo, no bloquea
    const condNombre = nombreVal.length > 0;
    const condMetodo = medioVal.length > 0;
    const condOperacion = pagoOk;
    const condComprobante = tipoEnvioVal.length > 0;
    const condContacto = contactoOk;
    const condMonto = montoOk;

    console.log(
      '[ProcesarVenta]',
      `Carrito(${carrito.length}): ${condCarrito} |`,
      `Doc(${documentoVal || 'vacío'}): ${condDocumento} (opcional) |`,
      `Nombre: ${condNombre} |`,
      `Metodo(${medioVal || 'ninguno'}): ${condMetodo} |`,
      `N°Operacion: ${condOperacion} |`,
      `Canal(${tipoEnvioVal}): ${condComprobante} |`,
      `Contacto: ${condContacto} |`,
      `Monto(${montoVal || 'vacio'}/${totalPagar.toFixed(2)}): ${condMonto}`
    );

    // Documento es OPCIONAL: no se incluye en la condición enabled
    const enabled = condCarrito && condNombre && condMetodo && condOperacion && condComprobante && condContacto && condMonto;
    if (btnProcesar) {
      if (isProcessingVenta) {
        btnProcesar.disabled = true;
        btnProcesar.style.opacity = '0.6';
      } else {
        btnProcesar.disabled = !enabled;
        btnProcesar.style.opacity = enabled ? '1' : '0.6';
      }
    }
  }

  // Exponer globalmente para que otras funciones (ej. actualizarTablaCarrito) puedan invocarla
  window.updateProcesarBtnState = updateProcesarBtnState;

  // wire events
  document.getElementById('cliente-documento').addEventListener('input', updateProcesarBtnState);
  document.getElementById('cliente-nombre').addEventListener('input', updateProcesarBtnState);
  if (medioPagoEl) medioPagoEl.addEventListener('change', actualizarPanelPago);
  if (inputMontoPagado) inputMontoPagado.addEventListener('input', updateProcesarBtnState);
  if (inputNumeroOperacion) inputNumeroOperacion.addEventListener('input', updateProcesarBtnState);
  if (tipoEnvioEl) tipoEnvioEl.addEventListener('change', actualizarPanelContacto);
  if (inputTelefono) inputTelefono.addEventListener('input', updateProcesarBtnState);
  if (inputCorreo) inputCorreo.addEventListener('input', updateProcesarBtnState);

  // Mostrar/ocultar paneles según el método de pago y tipo de comprobante
  actualizarPanelPago();
  actualizarPanelContacto();
  configurarSelectorComprobante(); // Selector inteligente de tipo comprobante (S/ 5.00)
  updateProcesarBtnState();

  inicializarBuscador(); // Iniciar la barra de búsqueda inteligente.
  inicializarCodigoBarras(); // Iniciar soporte de pistola lectora / código de barras.
  actualizarTablaCarrito(); // Mostrar estado inicial del carrito en la tabla.
});
