document.addEventListener("DOMContentLoaded", function () {
  const page = window.ReadMyPaperPage;

  if (page === "index") {
    initIndexPage();
  } else if (page === "job") {
    initJobPage();
  }

  function initIndexPage() {
    const voices = Array.isArray(window.__voices) ? window.__voices : [];
    const languageSelect = document.getElementById("language");
    const voiceSelect = document.getElementById("voice_key");
    const ttsEngineSelect = document.getElementById("tts_engine");
    const rateInput = document.getElementById("speech_rate");
    const rateOutput = document.getElementById("speech_rate_output");

    const renderVoices = () => {
      if (!languageSelect || !voiceSelect) return;
      const selectedLanguage = languageSelect.value;
      const selectedEngine = ttsEngineSelect?.value;
      const currentValue = voiceSelect.value;
      const filtered = voices.filter((voice) => {
        const languageCode = voice.language_code.toLowerCase();
        const matchesLanguage = selectedLanguage === "auto"
          || (selectedLanguage === "pt-BR" && languageCode.startsWith("pt"))
          || (selectedLanguage === "en" && languageCode.startsWith("en"))
          || !["auto", "pt-BR", "en"].includes(selectedLanguage);
        const matchesEngine = !selectedEngine || voice.engine === selectedEngine;
        return matchesLanguage && matchesEngine;
      });

      voiceSelect.innerHTML = "";
      voiceSelect.appendChild(new Option("Auto-select from detected language", "auto"));
      filtered.forEach((voice) => {
        const option = new Option(voice.display_name, voice.key);
        option.dataset.engine = voice.engine;
        voiceSelect.appendChild(option);
      });
      voiceSelect.value = [...voiceSelect.options].some((opt) => opt.value === currentValue)
        ? currentValue
        : "auto";
    };

    const renderRate = () => {
      if (rateInput && rateOutput) {
        rateOutput.textContent = `${Number(rateInput.value).toFixed(2)}×`;
      }
    };

    const llmCheckbox = document.getElementById("use_llm_cleaner");
    const llmOptions = document.getElementById("llm-options");
    if (llmCheckbox && llmOptions) {
      const renderLlmOptions = () => {
        llmOptions.classList.toggle("hidden", !llmCheckbox.checked);
      };
      llmCheckbox.addEventListener("change", renderLlmOptions);
      renderLlmOptions();
    }

    languageSelect?.addEventListener("change", renderVoices);
    ttsEngineSelect?.addEventListener("change", renderVoices);
    rateInput?.addEventListener("input", renderRate);
    renderVoices();
    renderRate();
  }

  function initJobPage() {
    const job = window.__job || {};
    const jobId = job.job_id;
    if (!jobId) return;

    const statusPill = document.getElementById("job-status-pill");
    const stepEl = document.getElementById("job-step");
    const progressLabel = document.getElementById("job-progress-label");
    const progressBar = document.getElementById("job-progress-bar");
    const errorBox = document.getElementById("job-error-box");
    const previewBox = document.getElementById("cleaned-text-preview");
    const actions = document.getElementById("job-actions");
    const audioCard = document.getElementById("audio-card");

    actions?.addEventListener("click", (event) => {
      const deleteButton = event.target.closest('[data-action="delete-job"]');
      if (!deleteButton) return;
      event.preventDefault();
      handleDeleteJob(jobId, deleteButton);
    });

    const updateJobView = (data) => {
      const result = data.result || {};
      statusPill.textContent = data.status;
      statusPill.className = `status-pill status-${data.status}`;
      stepEl.textContent = data.step;
      const percent = Math.round((data.progress || 0) * 100);
      progressLabel.textContent = `${percent}%`;
      progressBar.style.width = `${percent}%`;

      if (data.error) {
        errorBox.textContent = data.error;
        errorBox.classList.remove("hidden");
      } else {
        errorBox.textContent = "";
        errorBox.classList.add("hidden");
      }

      if (data.status === "completed" || data.status === "failed") {
        renderActions(jobId, actions, result, data.status);
      }

      if (data.status === "completed") {
        if (audioCard) {
          if (result.has_audio) {
            audioCard.classList.remove("hidden");
            const audio = audioCard.querySelector("audio");
            if (audio && !audio.getAttribute("src") && audio.querySelector("source") === null) {
              audio.setAttribute("src", `/jobs/${jobId}/audio`);
            }
            if (audio && audio.querySelector("source")) {
              audio.querySelector("source").setAttribute("src", `/jobs/${jobId}/audio`);
              audio.load();
            }
          } else {
            audioCard.classList.add("hidden");
          }
        }
        if (result.has_text && previewBox && previewBox.value.startsWith("Preview will appear")) {
          fetch(`/jobs/${jobId}/text`)
            .then((response) => response.ok ? response.text() : Promise.resolve(""))
            .then((text) => {
              if (text) previewBox.value = text.slice(0, 8000);
            })
            .catch(() => {});
        }
      }
    };

    const poll = () => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);
      fetch(`/api/jobs/${jobId}`, { signal: controller.signal, cache: "no-store" })
        .then((response) => {
          clearTimeout(timeoutId);
          return response.json();
        })
        .then((data) => {
          updateJobView(data);
          if (data.status === "completed" || data.status === "failed") {
            return;
          }
          window.setTimeout(poll, 2000);
        })
        .catch(() => {
          clearTimeout(timeoutId);
          window.setTimeout(poll, 3000);
        });
    };

    updateJobView(job);
    if (job.status !== "completed" && job.status !== "failed") {
      poll();
    }
  }

  function renderActions(jobId, actionsContainer, result, status) {
    if (!actionsContainer) return;
    actionsContainer.innerHTML = "";
    if (result.has_audio) {
      actionsContainer.appendChild(buildLink(`/jobs/${jobId}/audio`, "Download WAV"));
    }
    if (result.has_text) {
      actionsContainer.appendChild(buildLink(`/jobs/${jobId}/text`, "Download cleaned text"));
    }
    if (result.has_pdf) {
      actionsContainer.appendChild(buildLink(`/jobs/${jobId}/pdf`, "Download original PDF"));
    }
    if (status === "completed" || status === "failed") {
      actionsContainer.appendChild(buildButton("Delete job", "delete-job"));
    }
  }

  function buildLink(href, label) {
    const link = document.createElement("a");
    link.href = href;
    link.textContent = label;
    link.className = "button";
    return link;
  }

  function buildButton(label, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.className = "button";
    button.dataset.action = action;
    return button;
  }

  function handleDeleteJob(jobId, button) {
    if (!window.confirm("Delete this job and its files?")) {
      return;
    }

    button.disabled = true;
    fetch(`/jobs/${jobId}`, { method: "DELETE" })
      .then(async (response) => {
        if (response.ok) {
          window.location.assign("/");
          return;
        }

        let message = "Could not delete job.";
        try {
          const payload = await response.json();
          if (payload && payload.detail) {
            message = payload.detail;
          }
        } catch (_error) {
          // Ignore parse failures and fall back to the default message.
        }
        throw new Error(message);
      })
      .catch((error) => {
        button.disabled = false;
        const isNetworkError = error?.name === "TypeError"
          || /failed to fetch|networkerror|load failed/i.test(error?.message || "");
        window.alert(
          isNetworkError
            ? "Network error. Please check your connection."
            : error.message
        );
      });
  }
});
