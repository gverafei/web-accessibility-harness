// Discover model capabilities from the researcher's external Ollama server.
(() => {
  const server = document.getElementById('ollama_base_url');
  const model = document.getElementById('ollama_model');
  const refresh = document.getElementById('refreshOllamaModels');
  const status = document.getElementById('ollamaModelsStatus');
  if (!server || !model || !refresh || !status) return;
  const placeholder = model.options[0].text;
  let pending = null, finishBusy = null;
  const load = async (useSuggestedAddress = false) => {
    pending?.abort();
    finishBusy?.();
    finishBusy = null;
    const address = server.value.trim() || (useSuggestedAddress ? server.placeholder : '');
    if (!address) {
      pending = null;
      model.replaceChildren(new Option(placeholder, ''));
      status.textContent = '';
      refresh.disabled = false;
      return;
    }
    // A placeholder looks configured but is not submitted. An explicit probe
    // may use that suggested address, visibly, without persisting settings.
    if (!server.value.trim()) server.value = address;
    const selected = model.value;
    const controller = new AbortController();
    pending = controller;
    const timer = setTimeout(() => controller.abort(), 20000);
    finishBusy = globalThis.warpButtonBusy?.(refresh);
    refresh.disabled = true;
    status.textContent = '';
    try {
      const response = await fetch(refresh.dataset.modelsUrl, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({base_url: address}), signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || refresh.dataset.error);
      if (server.value.trim() !== address) return;
      model.replaceChildren(new Option(placeholder, ''));
      for (const item of data.models) model.add(new Option(item.name + ' · ' + (item.capabilities_verified === false ? refresh.dataset.unverifiedLabel : (item.vision ? refresh.dataset.visionLabel : refresh.dataset.textLabel)), item.id));
      if (data.models.some(item => item.id === selected)) model.value = selected;
      status.textContent = data.models.length ? refresh.dataset.success : refresh.dataset.empty;
    } catch (error) {
      if (pending === controller) status.textContent = error.name === 'AbortError' ? refresh.dataset.error : error.message;
    } finally {
      clearTimeout(timer);
      if (pending === controller) {
        finishBusy?.();
        finishBusy = null;
        refresh.disabled = false;
        pending = null;
      }
    }
  };
  server.addEventListener('change', () => load());
  refresh.addEventListener('click', () => load(true));
})();
