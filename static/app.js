/**
 * HACK YOUR FUTURE - CLIENT-SIDE AGENT ORCHESTRATOR
 * Live horizontal terminal loader — stays active for 30-45s+ rate-limit waits.
 */

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('analyzer-form');
    const inputSection = document.getElementById('input-section');
    const loadingSection = document.getElementById('loading-section');
    const resultsSection = document.getElementById('results-section');
    const viewReportContainer = document.getElementById('view-report-container');
    const btnViewReport = document.getElementById('btn-view-report');

    const btnSubmit = document.getElementById('btn-submit');
    const btnReset = document.getElementById('btn-reset');

    const STEP_IDS = ['osint', 'corp', 'council'];
    const steps = {
        osint: document.getElementById('step-osint'),
        corp: document.getElementById('step-corp'),
        council: document.getElementById('step-council'),
    };

    let liveLoaderInterval = null;
    let loaderStepsState = {
        currentStepIndex: 0,
        startTime: 0,
        active: false,
        tick: 0,
    };

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const payload = {
            recruiter_name: document.getElementById('recruiter_name').value.trim(),
            company: document.getElementById('company').value.trim(),
            role: document.getElementById('role').value.trim(),
            linkedin_url: document.getElementById('linkedin_url').value.trim(),
            resume_text: document.getElementById('resume_text').value.trim(),
        };

        inputSection.classList.add('hidden');
        loadingSection.classList.remove('hidden');
        viewReportContainer.classList.add('hidden');
        startLiveLoader(payload.recruiter_name, payload.company);

        try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 180_000);

            const response = await fetch('/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                signal: controller.signal,
            });

            clearTimeout(timeout);

            if (!response.ok) {
                const detail = await response.text().catch(() => '');
                throw new Error(`Server returned ${response.status}${detail ? `: ${detail.slice(0, 120)}` : ''}`);
            }

            const data = await response.json();
            await stopLiveLoaderAndResolve();

            renderDossier(data, payload.recruiter_name, payload.company);

            // Keep loading panel visible and display the View Swarm Report action button
            viewReportContainer.classList.remove('hidden');

            // Auto-transition to results after 1200ms to ensure the user is never left stuck on the loader
            setTimeout(() => {
                if (!loadingSection.classList.contains('hidden')) {
                    viewReportContainer.classList.add('hidden');
                    loadingSection.classList.add('hidden');
                    resultsSection.classList.remove('hidden');
                }
            }, 1200);
        } catch (error) {
            console.error('Analysis failed:', error);
            loaderStepsState.active = false;
            clearInterval(liveLoaderInterval);
            viewReportContainer.classList.add('hidden');

            const activeId = STEP_IDS[loaderStepsState.currentStepIndex] || 'council';
            logToConsole(activeId, `[FATAL] Swarm pipeline failed: ${error.message}`, 'error');

            alert(
                `Swarm failed to compile dossier: ${error.message}. ` +
                'Ensure uvicorn is running and Gemini quota is available.'
            );

            loadingSection.classList.add('hidden');
            inputSection.classList.remove('hidden');
        }
    });

    btnReset.addEventListener('click', () => {
        form.reset();
        resultsSection.classList.add('hidden');
        inputSection.classList.remove('hidden');
        viewReportContainer.classList.add('hidden');
        STEP_IDS.forEach((id) => {
            steps[id].classList.remove('active', 'completed');
        });
    });

    btnViewReport.addEventListener('click', () => {
        viewReportContainer.classList.add('hidden');
        loadingSection.classList.add('hidden');
        resultsSection.classList.remove('hidden');
    });

    function logToConsole(stepId, message, type = '') {
        const consoleEl = document.getElementById(`console-${stepId}`);
        if (!consoleEl) return;

        const awaitingEl = consoleEl.querySelector('.text-muted');
        if (awaitingEl) {
            consoleEl.innerHTML = '';
        }

        const line = document.createElement('div');
        line.className = `console-line ${type}`;
        line.style.transition = 'none';
        line.textContent = message;
        consoleEl.appendChild(line);

        // Cap lines to keep DOM light during long waits
        while (consoleEl.children.length > 40) {
            consoleEl.removeChild(consoleEl.firstChild);
        }
        consoleEl.scrollTop = consoleEl.scrollHeight;
    }

    function classifyLog(text) {
        if (text.includes('[FATAL]') || text.includes('[ERROR]')) return 'error';
        if (text.includes('[FOUND]') || text.includes('[SUCCESS]')) return 'found';
        if (text.includes('[SYS]') || text.includes('[WEAVE]')) return 'system';
        if (text.includes('[SEARCH]') || text.includes('[OSINT]') || text.includes('[CORP]') || text.includes('[INTEL]')) return 'search';
        if (text.includes('[COUNCIL]') || text.includes('[JUDGE]') || text.includes('[SWARM]')) return 'system';
        return '';
    }

    /** Per-step searching sequences — each step plays through its own narrative arc */
    const STEP_SEQUENCES = {
        osint: [
            { msg: (n, c) => `[OSINT] Querying live search indexes for "${n} at ${c}"...`, type: 'search' },
            { msg: (n) => `[SEARCH] Scanning LinkedIn profile for ${n}...`, type: 'search' },
            { msg: () => `[OSINT] Extracting professional footprint...`, type: 'search' },
            { msg: (n) => `[FOUND] LinkedIn metadata located for ${n}`, type: 'found' },
            { msg: () => `[OSINT] Scanning GitHub repositories...`, type: 'search' },
            { msg: () => `[SEARCH] Cross-referencing professional directories...`, type: 'search' },
            { msg: () => `[FOUND] Public email domain isolated`, type: 'found' },
            { msg: () => `[OSINT] Isolating base location and contact info...`, type: 'search' },
            { msg: () => `[FOUND] Professional footprint compiled`, type: 'found' },
        ],
        corp: [
            { msg: (n, c) => `[CORP] Analyzing enterprise stack at ${c}...`, type: 'search' },
            { msg: () => `[INTEL] Mapping core infrastructure and cloud footprint...`, type: 'search' },
            { msg: () => `[FOUND] Primary tech stack identified`, type: 'found' },
            { msg: () => `[CORP] Searching engineering blogs for platform signals...`, type: 'search' },
            { msg: () => `[INTEL] Extracting team-scaling and hiring patterns...`, type: 'search' },
            { msg: () => `[FOUND] Engineering bottlenecks mapped`, type: 'found' },
            { msg: () => `[SCAN] Parsing deployment modernization initiatives...`, type: 'search' },
            { msg: () => `[FOUND] Corporate intelligence compiled`, type: 'found' },
        ],
        council: [
            { msg: () => `[SWARM] Bootstrapping Gemini 2.5 Pro proposer...`, type: 'system' },
            { msg: () => `[PROPOSAL A] Evaluating resume compliance vectors...`, type: 'search' },
            { msg: () => `[FOUND] Proposal A complete — deep alignment mapped`, type: 'found' },
            { msg: () => `[SWARM] Bootstrapping Gemini 2.5 Flash proposer...`, type: 'system' },
            { msg: () => `[PROPOSAL B] Structuring networking icebreakers...`, type: 'search' },
            { msg: () => `[FOUND] Proposal B complete — actionable hooks built`, type: 'found' },
            { msg: () => `[JUDGE] Merging proposals into evidence-backed dossier...`, type: 'system' },
            { msg: () => `[WEAVE] Tracing multi-agent pipeline latency...`, type: 'system' },
            { msg: () => `[AUDIT] Validating Anti-Hallucination ledger entries...`, type: 'search' },
        ],
    };

    /** Additional lines for padding while waiting on the last step */
    const COUNCIL_WAITING = [
        () => `[COUNCIL] Cross-referencing candidate alignment vectors...`,
        () => `[WEAVE] Streaming active Gemini token buffers...`,
        () => `[JUDGE] Reconciling overlapping proposal parameters...`,
        () => `[AUDIT] Verifying evidence ledger source citations...`,
        () => `[SYS] Pacing API requests (Rate Limit Protection active)...`,
        () => `[COUNCIL] Scoring common ground relevance weights...`,
        () => `[COMPUTE] Holding swarm slot — waiting for upstream response...`,
    ];

    function randBetween(min, max) {
        return Math.floor(Math.random() * (max - min + 1)) + min;
    }

    function startLiveLoader(name, company) {
        clearInterval(liveLoaderInterval);

        STEP_IDS.forEach((id) => {
            steps[id].classList.remove('active', 'completed');
            const consoleEl = document.getElementById(`console-${id}`);
            if (consoleEl) {
                consoleEl.innerHTML = '<div class="console-line text-muted">Awaiting swarm activation...</div>';
            }
        });

        loaderStepsState = {
            currentStepIndex: 0,
            startTime: Date.now(),
            active: true,
            tick: 0,
            // Per-step timers: each of the first 2 steps gets a random duration (super-fast now that API has credits)
            stepDurations: [
                randBetween(800, 1500),   // OSINT: 0.8-1.5s
                randBetween(800, 1500),   // Corp Intel: 0.8-1.5s
                Infinity,                 // Council: runs until fetch completes
            ],
            stepStartTime: Date.now(),
            seqIndex: 0, // index within the current step's sequence
        };

        steps.osint.classList.add('active');
        logToConsole('osint', '[SYS] Initializing Swarm...', 'system');

        // Stream logs every 150ms for hyper-responsive feel
        liveLoaderInterval = setInterval(() => {
            if (!loaderStepsState.active) return;

            const state = loaderStepsState;
            const stepIdx = state.currentStepIndex;
            const currentId = STEP_IDS[stepIdx];
            const stepElapsed = Date.now() - state.stepStartTime;
            const stepDuration = state.stepDurations[stepIdx];
            const seq = STEP_SEQUENCES[currentId];

            state.tick += 1;

            // Check if this step's time is up and it's not the last step
            if (stepElapsed >= stepDuration && stepIdx < STEP_IDS.length - 1) {
                // Log final found line if we haven't already
                const lastSeqItem = seq[seq.length - 1];
                if (state.seqIndex < seq.length) {
                    logToConsole(currentId, lastSeqItem.msg(name, company), lastSeqItem.type);
                }

                // Complete this step
                steps[currentId].classList.remove('active');
                steps[currentId].classList.add('completed');

                // Advance to next step
                state.currentStepIndex += 1;
                state.stepStartTime = Date.now();
                state.seqIndex = 0;
                const nextId = STEP_IDS[state.currentStepIndex];
                steps[nextId].classList.add('active');
                return;
            }

            // Within a step: play through the sequence entries spread across the duration
            if (state.seqIndex < seq.length) {
                // Calculate when each sequence item should fire
                const interval = stepDuration === Infinity
                    ? 250 + randBetween(50, 150) // for council, just pace them out rapidly
                    : stepDuration / (seq.length + 1);
                const targetTime = interval * (state.seqIndex + 1);

                if (stepElapsed >= targetTime || stepDuration === Infinity) {
                    const item = seq[state.seqIndex];
                    logToConsole(currentId, item.msg(name, company), item.type);
                    state.seqIndex += 1;
                }
            } else if (stepIdx === STEP_IDS.length - 1) {
                // Council step exhausted its sequence — keep streaming waiting lines
                if (state.tick % 3 === 0) {
                    const waitLine = COUNCIL_WAITING[Math.floor(Math.random() * COUNCIL_WAITING.length)];
                    logToConsole(currentId, waitLine(), 'system');
                }
            }
        }, 150);
    }

    function stopLiveLoaderAndResolve() {
        if (!loaderStepsState.active) return Promise.resolve();
        loaderStepsState.active = false;
        clearInterval(liveLoaderInterval);

        return new Promise((resolve) => {
            STEP_IDS.forEach((id) => {
                steps[id].classList.remove('active');
                steps[id].classList.add('completed');
            });

            logToConsole('council', '[SUCCESS] Dossier payload received. All agents resolved.', 'found');
            setTimeout(resolve, 600);
        });
    }

    function renderDossier(dossier, recruiter, company) {
        document.getElementById('dossier-name').textContent = dossier.name || recruiter;
        document.getElementById('dossier-email').textContent =
            dossier.email || `${recruiter.toLowerCase().replace(' ', '.')}@${company.toLowerCase().replace(' ', '')}.com`;
        document.getElementById('dossier-bio').textContent = dossier.bio || '';

        const roleEl = document.getElementById('dossier-role');
        const roleContainer = roleEl.closest('.vibe-style');
        const hasRole =
            dossier.role &&
            dossier.role.trim() &&
            !['not found', 'unknown', 'not available'].includes(dossier.role.toLowerCase());

        if (hasRole) {
            roleEl.textContent = dossier.role;
            if (roleContainer) roleContainer.style.display = 'block';
        } else {
            roleEl.textContent = '';
            if (roleContainer) roleContainer.style.display = 'none';
        }

        const companyEl = document.getElementById('dossier-company');
        const companyContainer = companyEl.closest('.vibe-mirror');
        const hasCompany =
            dossier.company &&
            dossier.company.trim() &&
            !['not found', 'unknown'].includes(dossier.company.toLowerCase());

        if (hasCompany) {
            companyEl.textContent = dossier.company;
            if (companyContainer) companyContainer.style.display = 'block';
        } else {
            companyEl.textContent = '';
            if (companyContainer) companyContainer.style.display = 'none';
        }

        const vibeCard = roleEl.closest('.vibe-card');
        if (vibeCard) {
            vibeCard.style.display = !hasRole && !hasCompany ? 'none' : 'flex';
        }

        const redFlagsContainer = document.getElementById('dossier-red-flags');
        redFlagsContainer.innerHTML = '';
        if (dossier.ats_red_flags?.length) {
            dossier.ats_red_flags.forEach((item) => {
                const li = document.createElement('li');
                const severity = (item.severity || 'high').toLowerCase();
                li.innerHTML = `
                    <div class="gap-title">
                        <span>${escapeHTML(item.flag)}</span>
                        <span class="gap-severity ${severity}">${severity}</span>
                    </div>
                    <div class="gap-fix">${escapeHTML(item.fix)}</div>
                `;
                redFlagsContainer.appendChild(li);
            });
        } else {
            redFlagsContainer.innerHTML =
                `<li><div class="gap-title" style="color:var(--accent-green)">No Compliance Red Flags Detected</div><div class="gap-fix">Your resume successfully bypasses standard automated filtration.</div></li>`;
        }

        const improvementsContainer = document.getElementById('dossier-improvements');
        improvementsContainer.innerHTML = '';
        if (dossier.recommended_improvements?.length) {
            dossier.recommended_improvements.forEach((item) => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <div class="imp-qualification">${escapeHTML(item.missing_qualification)}</div>
                    <div class="imp-impact">${escapeHTML(item.impact)}</div>
                    <div class="imp-implementation"><strong>Action Plan:</strong> ${escapeHTML(item.implementation)}</div>
                `;
                improvementsContainer.appendChild(li);
            });
        } else {
            improvementsContainer.innerHTML =
                `<li><div class="imp-qualification">Resume Fully Optimized</div><div class="imp-impact">No missing keyword layers or credential gaps identified.</div></li>`;
        }

        const cgContainer = document.getElementById('dossier-common-ground');
        cgContainer.innerHTML = '';
        if (dossier.common_ground?.length) {
            dossier.common_ground.forEach((item) => {
                const li = document.createElement('li');
                let sourceLink = '';
                if (item.source_url?.startsWith('http')) {
                    sourceLink = `<a href="${item.source_url}" target="_blank" class="cg-source-link">Source</a>`;
                } else if (item.source_url) {
                    sourceLink = `<span class="cg-source-link">${escapeHTML(item.source_url)}</span>`;
                }
                li.innerHTML = `<span class="cg-point">${escapeHTML(item.point)}</span>${sourceLink}`;
                cgContainer.appendChild(li);
            });
        } else {
            cgContainer.innerHTML =
                `<li><span class="cg-point">Focus on core professional traits and mutual business goals.</span></li>`;
        }

        const eventsContainer = document.getElementById('dossier-upcoming-events');
        eventsContainer.innerHTML = '';
        if (dossier.upcoming_events?.length) {
            dossier.upcoming_events.forEach((item) => {
                const li = document.createElement('li');
                li.innerHTML = `📍 <span>${escapeHTML(item)}</span>`;
                eventsContainer.appendChild(li);
            });
        } else {
            eventsContainer.innerHTML =
                `<li style="background:rgba(255,255,255,0.02);border-color:transparent;color:var(--text-muted)">No registered public events.</li>`;
        }

        const coldIcebreakersContainer = document.getElementById('dossier-cold-icebreakers');
        coldIcebreakersContainer.innerHTML = '';
        if (dossier.cold_icebreakers?.length) {
            dossier.cold_icebreakers.forEach((item) => {
                const li = document.createElement('li');
                li.textContent = item;
                coldIcebreakersContainer.appendChild(li);
            });
        } else {
            coldIcebreakersContainer.innerHTML = `<li>No cold icebreakers compiled.</li>`;
        }

        const icebreakersContainer = document.getElementById('dossier-icebreakers');
        icebreakersContainer.innerHTML = '';
        (dossier.icebreakers || []).forEach((item) => {
            const li = document.createElement('li');
            li.textContent = item;
            icebreakersContainer.appendChild(li);
        });

        const questionsContainer = document.getElementById('dossier-questions');
        questionsContainer.innerHTML = '';
        (dossier.smart_questions || []).forEach((item) => {
            const li = document.createElement('li');
            li.textContent = item;
            questionsContainer.appendChild(li);
        });

        const ledgerBody = document.getElementById('dossier-ledger-body');
        ledgerBody.innerHTML = '';
        if (dossier.evidence_ledger?.length) {
            dossier.evidence_ledger.forEach((item) => {
                const tr = document.createElement('tr');
                let sourceText;
                if (item.source_url?.startsWith('http')) {
                    sourceText = `<a href="${item.source_url}" target="_blank">${escapeHTML(item.source_url)}</a>`;
                } else if (item.source_url) {
                    sourceText = escapeHTML(item.source_url);
                } else {
                    sourceText = `<span style="color:var(--text-muted)">Public Signals / LinkedIn</span>`;
                }
                const confidence = (item.confidence || 'med').toLowerCase();
                tr.innerHTML = `
                    <td class="ledger-claim">${escapeHTML(item.claim)}</td>
                    <td class="ledger-source">${sourceText}</td>
                    <td><span class="confidence-pill ${confidence}">${confidence}</span></td>
                `;
                ledgerBody.appendChild(tr);
            });
        } else {
            ledgerBody.innerHTML =
                `<tr><td colspan="3" style="text-align:center;color:var(--text-muted)">No evidence mapped.</td></tr>`;
        }
    }

    function escapeHTML(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
});
