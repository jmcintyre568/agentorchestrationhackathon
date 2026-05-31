/**
 * HACK YOUR FUTURE - CLIENT-SIDE AGENT ORCHESTRATOR
 */

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('analyzer-form');
    const inputSection = document.getElementById('input-section');
    const loadingSection = document.getElementById('loading-section');
    const resultsSection = document.getElementById('results-section');
    
    const btnSubmit = document.getElementById('btn-submit');
    const btnReset = document.getElementById('btn-reset');
    
    // Timeline steps for loader animation
    const steps = {
        osint: document.getElementById('step-osint'),
        corp: document.getElementById('step-corp'),
        council: document.getElementById('step-council'),
        judge: document.getElementById('step-judge')
    };

    let loadingInterval = null;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        // Gather input values
        const payload = {
            recruiter_name: document.getElementById('recruiter_name').value.trim(),
            company: document.getElementById('company').value.trim(),
            role: document.getElementById('role').value.trim(),
            linkedin_url: document.getElementById('linkedin_url').value.trim(),
            resume_text: document.getElementById('resume_text').value.trim()
        };

        // Transition: Inputs -> Loading Panel
        inputSection.classList.add('hidden');
        loadingSection.classList.remove('hidden');
        
        // Start the minimum loader animation sequence
        const loaderPromise = animateLoaderSteps();

        try {
            // Trigger API request in parallel
            const apiPromise = fetch('/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            }).then(async (response) => {
                if (!response.ok) {
                    throw new Error(`Server returned status: ${response.status}`);
                }
                return response.json();
            });

            // Wait for BOTH the API response and the loader sequence to finish
            const [data, _] = await Promise.all([apiPromise, loaderPromise]);
            
            // Render dossier results
            renderDossier(data, payload.recruiter_name, payload.company);
            
            // Transition: Loading -> Results Panel
            loadingSection.classList.add('hidden');
            resultsSection.classList.remove('hidden');

        } catch (error) {
            console.error('Analysis failed:', error);
            clearInterval(loadingInterval);
            alert(`Swarm failed to compile dossier: ${error.message}. Check that your backend uvicorn server is active!`);
            
            // Reset back to inputs
            loadingSection.classList.add('hidden');
            inputSection.classList.remove('hidden');
        }
    });

    btnReset.addEventListener('click', () => {
        // Reset form inputs
        form.reset();
        
        // Transition: Results -> Inputs Panel
        resultsSection.classList.add('hidden');
        inputSection.classList.remove('hidden');
        
        // Reset loader step states
        Object.values(steps).forEach(step => {
            step.classList.remove('active', 'completed');
        });
    });

    /**
     * Simulates step-by-step progress through the subagent swarm to match real backend delay
     */
    function animateLoaderSteps() {
        return new Promise((resolve) => {
            // Reset
            Object.values(steps).forEach(step => {
                step.classList.remove('active', 'completed');
            });

            // Step 1: OSINT Active
            steps.osint.classList.add('active');

            setTimeout(() => {
                steps.osint.classList.remove('active');
                steps.osint.classList.add('completed');
                steps.corp.classList.add('active');
                
                setTimeout(() => {
                    steps.corp.classList.remove('active');
                    steps.corp.classList.add('completed');
                    steps.council.classList.add('active');
                    
                    setTimeout(() => {
                        steps.council.classList.remove('active');
                        steps.council.classList.add('completed');
                        steps.judge.classList.add('active');
                        
                        setTimeout(() => {
                            steps.judge.classList.remove('active');
                            steps.judge.classList.add('completed');
                            resolve(); // Animation finished!
                        }, 1200);
                    }, 1200);
                }, 1200);
            }, 1200);
        });
    }

    /**
     * Renders Dossier JSON values dynamically into semantic HTML component structures
     */
    function renderDossier(dossier, recruiter, company) {
        // Scanned Digital Footprint Content
        document.getElementById('dossier-name').textContent = dossier.name || recruiter;
        document.getElementById('dossier-email').textContent = dossier.email || `${recruiter.toLowerCase().replace(' ', '.')}@${company.toLowerCase().replace(' ', '')}.com`;
        document.getElementById('dossier-bio').textContent = dossier.bio || '';
        document.getElementById('dossier-role').textContent = dossier.role || 'Senior Lead';
        document.getElementById('dossier-company').textContent = dossier.company || company;



        // ATS Red Flags (Critical Gaps)
        const redFlagsContainer = document.getElementById('dossier-red-flags');
        redFlagsContainer.innerHTML = '';
        if (dossier.ats_red_flags && dossier.ats_red_flags.length > 0) {
            dossier.ats_red_flags.forEach(item => {
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
            redFlagsContainer.innerHTML = `<li><div class="gap-title" style="color:var(--accent-green)">No Compliance Red Flags Detected</div><div class="gap-fix">Your resume successfully bypasses standard automated filtration.</div></li>`;
        }

        // Recommended Structural Improvements
        const improvementsContainer = document.getElementById('dossier-improvements');
        improvementsContainer.innerHTML = '';
        if (dossier.recommended_improvements && dossier.recommended_improvements.length > 0) {
            dossier.recommended_improvements.forEach(item => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <div class="imp-qualification">${escapeHTML(item.missing_qualification)}</div>
                    <div class="imp-impact">${escapeHTML(item.impact)}</div>
                    <div class="imp-implementation"><strong>Action Plan:</strong> ${escapeHTML(item.implementation)}</div>
                `;
                improvementsContainer.appendChild(li);
            });
        } else {
            improvementsContainer.innerHTML = `<li><div class="imp-qualification">Resume Fully Optimized</div><div class="imp-impact">No missing keyword layers or credential gaps identified.</div></li>`;
        }

        // Common Ground
        const cgContainer = document.getElementById('dossier-common-ground');
        cgContainer.innerHTML = '';
        if (dossier.common_ground && dossier.common_ground.length > 0) {
            dossier.common_ground.forEach(item => {
                const li = document.createElement('li');
                
                let sourceLink = '';
                if (item.source_url && item.source_url.startsWith('http')) {
                    sourceLink = `<a href="${item.source_url}" target="_blank" class="cg-source-link">Source</a>`;
                } else if (item.source_url) {
                    sourceLink = `<span class="cg-source-link">${escapeHTML(item.source_url)}</span>`;
                }
                
                li.innerHTML = `
                    <span class="cg-point">${escapeHTML(item.point)}</span>
                    ${sourceLink}
                `;
                cgContainer.appendChild(li);
            });
        } else {
            cgContainer.innerHTML = `<li><span class="cg-point">Focus on core professional traits and mutual business goals.</span></li>`;
        }

        // Icebreakers
        const icebreakersContainer = document.getElementById('dossier-icebreakers');
        icebreakersContainer.innerHTML = '';
        if (dossier.icebreakers && dossier.icebreakers.length > 0) {
            dossier.icebreakers.forEach(item => {
                const li = document.createElement('li');
                li.textContent = item;
                icebreakersContainer.appendChild(li);
            });
        }

        // Smart Questions
        const questionsContainer = document.getElementById('dossier-questions');
        questionsContainer.innerHTML = '';
        if (dossier.smart_questions && dossier.smart_questions.length > 0) {
            dossier.smart_questions.forEach(item => {
                const li = document.createElement('li');
                li.textContent = item;
                questionsContainer.appendChild(li);
            });
        }

        // Evidence Ledger Body
        const ledgerBody = document.getElementById('dossier-ledger-body');
        ledgerBody.innerHTML = '';
        if (dossier.evidence_ledger && dossier.evidence_ledger.length > 0) {
            dossier.evidence_ledger.forEach(item => {
                const tr = document.createElement('tr');
                
                let sourceText = 'Public Signals';
                if (item.source_url && item.source_url.startsWith('http')) {
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
            ledgerBody.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--text-muted)">No evidence mapped.</td></tr>`;
        }
    }

    /**
     * Prevents XSS injection when rendering dynamic content
     */
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
