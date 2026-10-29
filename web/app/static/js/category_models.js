/* Read-only configured choices; selecting a model never starts a classifier. */
(() => {
  const config = JSON.parse(document.getElementById('managedUrlConfig').textContent);
  const select = document.getElementById('categoryModel');
  const start = document.getElementById('startCategorization');
  const status = document.getElementById('categoryModelsStatus');
  const job = JSON.parse(document.getElementById('categoryAutomation').dataset.job || '{}');
  const active = ['queued', 'running', 'stopping'].includes(job.status);
  const update = () => {
    const option = [...select.options].find(item => item.value === select.value);
    select.title = option?.text || '';
    start.disabled = active || !option || option.disabled || !select.value || !Number(start.dataset.missingCount);
  };
  select.addEventListener('change', update);
  (async () => {
    try {
      const response = await fetch(config.modelsUrl, {headers: {Accept: 'application/json'}});
      if (!response.ok) throw new Error(config.noModels);
      const data = await response.json();
      const placeholder = new Option(config.chooseModel, '');
      placeholder.disabled = true;
      select.replaceChildren(placeholder);
      for (const item of data.models) {
        const label = [item.label, item.is_default ? config.defaultLabel : '',
          item.provider === 'local' ? config.localLabel : config.cloudLabel,
          item.enabled ? '' : config.keyRequired].filter(Boolean).join(' · ');
        const option = new Option(label, item.id);
        option.disabled = !item.enabled;
        option.title = label;
        select.add(option);
      }
      const preferred = data.models.find(item => item.is_default && item.enabled);
      select.value = preferred?.id || '';
      if (active) {
        const snapshot = typeof job.model_config_json === 'string' ? JSON.parse(job.model_config_json) : job.model_config_json;
        const id = snapshot?.choice_id || job.model;
        if (![...select.options].some(item => item.value === id)) select.add(new Option(job.model, id));
        select.value = id;
      }
      select.disabled = active || !data.models.some(item => item.enabled);
      status.textContent = data.local_error ? config.localModelsError :
        data.models.some(item => item.enabled) ? '' : config.noModels;
      update();
    } catch (_error) {
      select.disabled = true;
      start.disabled = true;
      status.textContent = config.noModels;
    }
  })();
})();
