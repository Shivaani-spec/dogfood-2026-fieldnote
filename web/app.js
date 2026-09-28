(function () {
  "use strict";
  var state = {
    event: null, events: [], user: null, projects: [], tracks: [], metrics: {},
    view: "gallery", mine: [], teams: [], assignments: [], selectedAssignment: "",
    organizerResults: [], publicResults: null, audit: [], judges: [], ballot: null, editingProject: null,
    authMode: "login", pendingInvite: ""
  };
  var labels = { gallery: "Project gallery", submit: "Submit project", judging: "Judge desk", organizer: "Event control" };
  var criterionInfo = {
    functionality: ["Functionality", "Does the project work and solve its stated problem?"],
    quality: ["Craft & quality", "Is the implementation thoughtful, clear and dependable?"],
    innovation: ["Originality", "What is new or surprising about the approach?"],
    impact: ["Potential impact", "How useful could this be for its intended audience?"]
  };
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[char];
    });
  }
  function api(path, options) {
    options = options || {};
    var headers = options.headers || {};
    if (options.body && typeof options.body !== "string") {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    options.headers = headers;
    options.credentials = "same-origin";
    return fetch(path, options).then(function (response) {
      var type = response.headers.get("content-type") || "";
      return (type.indexOf("application/json") >= 0 ? response.json() : response.text()).then(function (data) {
        if (!response.ok) {
          var message = data && data.message ? data.message : "Request failed (" + response.status + ").";
          var error = new Error(message);
          error.status = response.status;
          throw error;
        }
        return data;
      });
    });
  }
  function notice(message, error) {
    var node = document.getElementById("notice");
    node.textContent = message;
    node.className = "notice show" + (error ? " error" : "");
    clearTimeout(notice.timer);
    notice.timer = setTimeout(function () { node.className = "notice"; }, 3400);
  }
  function titleDate(value) {
    if (!value) return "To be announced";
    var date = new Date(value);
    if (isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(date) +
      " · " + new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }).format(date);
  }
  function inputDate(value) {
    if (!value) return "";
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }
  function utcValue(value) {
    return value ? new Date(value).toISOString() : "";
  }
  function initials(value) {
    return String(value || "G").trim().split(/\s+/).slice(0, 2).map(function (word) {
      return word.charAt(0);
    }).join("").toUpperCase();
  }
  function safeLink(url, label) {
    if (!url || !/^https?:\/\//i.test(url)) return "";
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(label) + ' ↗</a>';
  }
  function setNav(view) {
    state.view = view;
    document.querySelectorAll(".view").forEach(function (node) { node.classList.add("hidden"); });
    document.getElementById("view-" + view).classList.remove("hidden");
    document.querySelectorAll("[data-view]").forEach(function (node) {
      node.classList.toggle("active", node.getAttribute("data-view") === view);
    });
    document.getElementById("view-label").textContent = labels[view];
    if (view === "gallery") renderGallery();
    if (view === "submit") renderSubmit();
    if (view === "judging") renderJudging();
    if (view === "organizer") renderOrganizer();
  }
  function applyUser(user) {
    state.user = user;
    document.getElementById("profile-name").textContent = user ? user.name : "Guest";
    document.getElementById("profile-role").textContent = user ? user.role : "Visitor access";
    document.getElementById("profile-avatar").textContent = initials(user ? user.name : "Guest");
    document.getElementById("sign-in").textContent = user ? "Sign out" : "Sign in";
    document.querySelectorAll('.nav-link[data-view="judging"]').forEach(function (node) {
      node.querySelector(".nav-pip").style.background = user && user.role === "judge" ? "#afd77e" : "#555950";
    });
  }
  function refresh() {
    return api("/api/bootstrap").then(function (data) {
      state.event = data.event;
      state.events = data.events || [];
      state.user = data.user;
      state.projects = data.projects || [];
      state.tracks = data.tracks || [];
      state.metrics = data.metrics || {};
      document.getElementById("event-name").textContent = data.event.name;
      document.getElementById("project-count").textContent = data.projects.length;
      applyUser(data.user);
      var published = data.event.results_published;
      return (published ? api("/api/results").catch(function () { return null; }) : Promise.resolve(null))
        .then(function (publicData) {
          state.publicResults = publicData ? publicData.results || [] : null;
          if (state.view === "gallery") renderGallery();
          if (state.view === "organizer") renderOrganizer();
        });
    }).catch(function (error) {
      notice(error.message, true);
    });
  }
  function eventBanner() {
    if (!state.event) return "";
    var phase = state.event.submission_open ? "SUBMISSIONS OPEN" : "EVENT WORKSPACE";
    return '<div class="event-banner"><div class="banner-copy">' +
      '<div class="banner-kicker"><span></span>' + phase + ' <b>·</b> ' + esc(state.event.name) + '</div>' +
      '<h2>Good ideas deserve a fair shot.</h2>' +
      '<p>One place for teams to share what they made and for judges to make a careful call.</p></div>' +
      '<div class="banner-meta"><small>SUBMISSIONS CLOSE</small><strong>' + esc(titleDate(state.event.submissions_close)) +
      '</strong><em>' + (state.event.submission_open ? "Entries are being accepted" : "Submission window closed") + '</em></div></div>';
  }
  function projectCard(project) {
    var tags = (project.tech_tags || []).slice(0, 3).map(function (tag) {
      return '<span class="tech-tag">' + esc(tag) + '</span>';
    }).join("");
    return '<article class="project-card"><div class="card-top"><span class="track-chip">' + esc(project.track) +
      '</span><span class="project-id">' + esc(project.id) + '</span></div>' +
      '<h3>' + esc(project.title) + '</h3><p class="team">by ' + esc(project.team_name) + '</p>' +
      '<p class="tagline">' + esc(project.tagline || "A team submission.") + '</p>' +
      '<div class="tag-row">' + tags + '</div><div class="card-bottom">' +
      (project.repo_url ? safeLink(project.repo_url, "Source") : '<span class="card-link">Project details</span>') +
      '<button class="card-open" type="button" data-open-project="' + esc(project.id) + '">View project →</button></div></article>';
  }
  function renderGallery() {
    var node = document.getElementById("view-gallery");
    var trackOptions = '<option value="">All tracks</option>' + state.tracks.map(function (track) {
      return '<option value="' + esc(track.id) + '">' + esc(track.name) + '</option>';
    }).join("");
    var cards = state.projects.map(projectCard).join("");
    var publishedResults = state.publicResults ? '<section class="panel" style="margin:0 0 20px"><div class="panel-head"><div><h3>Published results</h3><p>Weighted judge scores and community credits</p></div><span class="pill pill-accent">OFFICIAL</span></div>' +
      '<div class="table-wrap"><table class="data-table"><thead><tr><th>Rank</th><th>Project</th><th>Track</th><th>Adjusted</th><th>Reviews</th><th>Community credits</th></tr></thead><tbody>' +
      state.publicResults.map(function (item, index) {
        var trackItem = state.tracks.filter(function (track) { return track.id === item.track_id; })[0];
        return '<tr><td><span class="score-pill">#' + (index + 1) + '</span></td><td><strong>' + esc(item.title) +
          '</strong></td><td>' + esc(trackItem ? trackItem.name : item.track_id) + '</td><td>' +
          (item.normalized_score == null ? "—" : Number(item.normalized_score).toFixed(2)) + '</td><td>' +
          Number(item.review_count || 0) + '</td><td>' + Number(item.community_credits || 0) + '</td></tr>';
      }).join("") + '</tbody></table></div></section>' : "";
    node.innerHTML = '<div class="page-heading"><div><h1>Project gallery</h1>' +
      '<p>Meet the teams and ideas in this event. Search across project names and descriptions, then explore each build.</p></div>' +
      '<div class="heading-note"><span>↗</span> PUBLIC VIEW · ' + String(state.projects.length).padStart(2, "0") + ' ENTRIES</div></div>' +
      eventBanner() +
      '<div class="toolbar"><div class="search-wrap"><input id="gallery-search" class="search-input" type="search" placeholder="Search projects, teams, ideas…" aria-label="Search projects"></div>' +
      '<select id="gallery-track" class="select-control filter-select" aria-label="Filter by track">' + trackOptions + '</select>' +
      '<button class="button button-ghost button-small" data-action="ballot">Community ballot</button>' +
      '<span class="result-count" id="gallery-count">' + state.projects.length + ' projects</span></div>' +
      (state.ballot ? ballotPanel() : "") + publishedResults +
      '<div class="section-caption"><h3>All submissions</h3><span>NEWEST FIRST · ' + (state.event.results_published ? "RESULTS PUBLISHED" : "RESULTS PRIVATE") + '</span></div>' +
      '<div id="project-grid" class="project-grid">' + (cards || '<div class="empty-state"><strong>No projects match</strong>Try a different search or track.</div>') + '</div>';
    var search = document.getElementById("gallery-search");
    var track = document.getElementById("gallery-track");
    search.addEventListener("input", filterGallery);
    track.addEventListener("change", filterGallery);
  }
  function filterGallery() {
    var query = document.getElementById("gallery-search").value.trim();
    var track = document.getElementById("gallery-track").value;
    api("/api/projects?q=" + encodeURIComponent(query) + "&track=" + encodeURIComponent(track))
      .then(function (data) {
        state.projects = data.projects || [];
        document.getElementById("project-grid").innerHTML = state.projects.map(projectCard).join("") ||
          '<div class="empty-state"><strong>No projects match</strong>Try a different search or track.</div>';
        document.getElementById("gallery-count").textContent = state.projects.length + " projects";
        document.getElementById("project-count").textContent = state.projects.length;
      }).catch(function (error) { notice(error.message, true); });
  }
  function ballotPanel() {
    var ballot = state.ballot;
    if (!ballot) return "";
    var cards = ballot.projects.map(function (project) {
      return '<div class="assignment-row"><span class="assignment-initial">♡</span><span class="assignment-copy"><strong>' +
        esc(project.title) + '</strong><small>' + esc(project.track) + ' · ' +
        (project.my_vote_credits ? "your current vote: " + project.my_vote_credits + " credits" : "not voted") +
        '</small></span><select class="select-control" data-vote-credit="' + esc(project.id) + '">' +
        '<option value="0">No vote</option><option value="1">1 credit · 1 voice</option><option value="2">2 credits · 1.41 voice</option>' +
        '<option value="3">3 credits · 1.73 voice</option><option value="4">4 credits · 2 voice</option></select>' +
        '<button class="button button-primary button-small" data-vote="' + esc(project.id) + '">Save</button></div>';
    }).join("");
    return '<section class="panel panel-pad" style="margin:0 0 20px"><div class="section-caption" style="margin-top:0">' +
      '<h3>Community ballot</h3><span>QUADRATIC · ' + ballot.credits_spent + ' / 16 CREDITS USED</span></div>' +
      '<p class="form-help">Spend up to 16 credits across your ballot. Each vote costs credits squared, so a concentrated vote has a smaller influence than its cost.</p>' +
      '<div class="assignment-list" style="margin-top:12px">' + cards + '</div></section>';
  }
  function renderSubmit(project) {
    if (project) state.editingProject = project;
    var edit = state.editingProject;
    var p = edit || {};
    var node = document.getElementById("view-submit");
    var questionFields = (state.event.questions || []).map(function (question) {
      var value = p.answers && p.answers[question.key] ? p.answers[question.key] : "";
      return '<div class="form-field full"><label>' + esc(question.label) +
        (question.required ? '<span>required</span>' : "") + '</label>' +
        (question.type === "long_text" ?
          '<textarea name="answer_' + esc(question.key) + '" class="text-control" ' +
          (question.required ? "required" : "") + '>' + esc(value) + '</textarea>' :
          '<input name="answer_' + esc(question.key) + '" class="field-control" ' +
          (question.required ? "required" : "") + ' value="' + esc(value) + '">') + '</div>';
    }).join("");
    var select = state.tracks.map(function (track) {
      return '<option value="' + esc(track.id) + '" ' + (p.track_id === track.id ? "selected" : "") + '>' +
        esc(track.name) + '</option>';
    }).join("");
    var owned = state.mine.map(function (item) {
      return '<div class="assignment-row"><span class="assignment-initial">↗</span><span class="assignment-copy"><strong>' +
        esc(item.title) + '</strong><small>' + esc(item.status) + ' · updated ' + esc(titleDate(item.updated_at)) +
        '</small></span><button class="button button-ghost button-small" data-edit-project="' + esc(item.id) + '">Edit</button></div>';
    }).join("");
    var guest = !state.user || state.user.role !== "participant";
    node.innerHTML = '<div class="page-heading"><div><h1>' + (edit ? "Edit your project" : "Submit your project") + '</h1>' +
      '<p>Tell the story of what you made. Save a draft whenever you need; you can update your entry until the deadline.</p></div>' +
      '<span class="pill ' + (state.event.submission_open ? "pill-accent" : "pill-warm") + '">' +
      (state.event.submission_open ? "SUBMISSIONS OPEN" : "SUBMISSIONS CLOSED") + '</span></div>' +
      '<div class="split-layout"><section class="panel panel-pad"><div class="section-caption" style="margin-top:0"><h3>Project details</h3><span>STEP 01 / 02</span></div>' +
      (guest ? '<div class="notice-line">Participant access is required to create and edit a submission. Sign in or create a participant account to continue.</div>' : "") +
      '<form id="project-form" data-form="project" class="form-grid" style="margin-top:16px">' +
      '<div class="form-field"><label for="project-title">Project name <span>required</span></label><input id="project-title" name="title" class="field-control" maxlength="120" required value="' + esc(p.title) + '" placeholder="e.g. Quiet Hours"></div>' +
      '<div class="form-field"><label for="project-track">Track <span>required</span></label><select id="project-track" name="track_id" class="select-control" required>' + select + '</select></div>' +
      '<div class="form-field full"><label for="project-tagline">One-line pitch <span>200 characters</span></label><input id="project-tagline" name="tagline" class="field-control" maxlength="200" value="' + esc(p.tagline) + '" placeholder="The problem you solve, in one clear sentence."></div>' +
      '<div class="form-field full"><label for="project-description">Project story <span>what it does, how it works, who it helps</span></label><textarea id="project-description" name="description" class="text-control textarea" maxlength="8000" placeholder="Give reviewers enough context to understand the work.">' + esc(p.description) + '</textarea></div>' +
      '<div class="form-field"><label for="project-repo">Repository URL</label><input id="project-repo" name="repo_url" type="url" class="field-control" value="' + esc(p.repo_url) + '" placeholder="https://github.com/team/project"></div>' +
      '<div class="form-field"><label for="project-live">Live demo URL</label><input id="project-live" name="live_url" type="url" class="field-control" value="' + esc(p.live_url) + '" placeholder="https://project.example"></div>' +
      '<div class="form-field"><label for="project-video">Demo video URL</label><input id="project-video" name="demo_url" type="url" class="field-control" value="' + esc(p.demo_url) + '" placeholder="A hosted walkthrough"></div>' +
      '<div class="form-field"><label for="project-thumb">Thumbnail URL</label><input id="project-thumb" name="thumbnail_url" type="url" class="field-control" value="' + esc(p.thumbnail_url) + '" placeholder="https://…"></div>' +
      '<div class="form-field full"><label for="project-tags">Technology tags <span>comma separated</span></label><input id="project-tags" name="tech_tags" class="field-control" value="' + esc((p.tech_tags || []).join(", ")) + '" placeholder="Python, SQLite, accessibility"></div>' +
      '<div class="form-field full"><label for="project-gallery">Image gallery <span>up to 12 URLs, one per line</span></label><textarea id="project-gallery" name="gallery" class="text-control" style="min-height:70px">' +
      esc((p.gallery || []).join("\n")) + '</textarea></div>' + questionFields +
      '<div class="form-actions full"><p>Edits close at ' + esc(titleDate(state.event.submissions_close)) + '.</p><div class="toolbar-actions">' +
      (edit ? '<button type="button" class="button button-ghost" data-action="cancel-edit">Cancel</button>' : "") +
      '<button class="button button-ghost" type="submit" data-status="draft">Save draft</button>' +
      '<button class="button button-primary" type="submit" data-status="submitted">' + (edit ? "Update entry" : "Submit project") + ' <span>→</span></button>' +
      '</div></div></form></section>' +
      '<aside><section class="panel"><div class="panel-head"><div><h3>Your team</h3><p>Invite people working with you</p></div></div><div class="panel-pad">' +
      '<div class="assignment-list">' + (state.teams.length ? state.teams.map(function (team) {
        return '<div class="assignment-row"><span class="assignment-initial">♧</span><span class="assignment-copy"><strong>' +
          esc(team.name) + '</strong><small>' + esc(team.id) + '</small></span>' +
          '<button class="button button-ghost button-small" data-invite-team="' + esc(team.id) + '">Invite</button></div>';
      }).join("") : '<div class="empty-state"><strong>No team yet</strong>Create a team to start a submission.</div>') + '</div>' +
      '<form id="team-form" data-form="team" class="form-grid" style="margin-top:15px"><div class="form-field full"><label>New team name</label><input name="name" class="field-control" required maxlength="100" placeholder="A name your teammates will remember"></div><div class="form-field full"><button class="button button-dark" type="submit">Create team</button></div></form>' +
      '</div></section><section class="panel" style="margin-top:13px"><div class="panel-head"><div><h3>Your submissions</h3><p>Drafts and entries for this event</p></div><span class="pill">' + state.mine.length + '</span></div><div class="panel-pad"><div class="assignment-list">' +
      (owned || '<div class="empty-state"><strong>Nothing submitted yet</strong>Your entries will show here.</div>') +
      '</div></div></section></aside></div>';
    if (guest) {
      node.querySelectorAll("#project-form input,#project-form textarea,#project-form select,#project-form button").forEach(function (field) { field.disabled = true; });
      node.querySelector("#team-form").classList.add("hidden");
    }
    if (!state.mine.length && state.user && state.user.role === "participant") loadMine();
    if (!state.teams.length && state.user && state.user.role === "participant") loadTeams();
  }
  function loadMine() {
    return api("/api/my/projects").then(function (data) {
      state.mine = data.projects || [];
      if (state.view === "submit") renderSubmit();
    }).catch(function () {});
  }
  function loadTeams() {
    return api("/api/my/teams").then(function (data) {
      state.teams = data.teams || [];
      if (state.view === "submit") renderSubmit();
    }).catch(function () {});
  }
  function scoreButton(criterion, value) {
    var content = "";
    for (var score = 1; score <= 5; score++) {
      content += '<button class="score-option ' + (Number(value) === score ? "chosen" : "") +
        '" type="button" data-score="' + esc(criterion) + '" data-value="' + score + '" aria-label="' +
        esc((criterionInfo[criterion] || [criterion])[0]) + ': ' + score + ' out of 5">' + score + '</button>';
    }
    return content;
  }
  function renderJudging() {
    var node = document.getElementById("view-judging");
    if (!state.user || !["judge","organizer","admin"].includes(state.user.role)) {
      node.innerHTML = '<div class="page-heading"><div><h1>Judge desk</h1><p>Your review queue and private ballots live here.</p></div></div>' +
        '<div class="empty-state"><strong>Judge access required</strong>Use a judge invitation or a seeded judge account to open the review queue.' +
        '<p><button class="button button-dark" data-demo="judge">Sign in as a demo judge</button></p></div>';
      return;
    }
    var selected = state.assignments.find(function (item) { return item.assignment_id === state.selectedAssignment; }) ||
      state.assignments.find(function (item) { return !item.criteria || !Object.keys(item.criteria).length; }) ||
      state.assignments[0];
    if (selected) state.selectedAssignment = selected.assignment_id;
    var queue = state.assignments.map(function (item) {
      var done = item.criteria && Object.keys(item.criteria).length;
      return '<button class="assignment-row ' + (selected && selected.assignment_id === item.assignment_id ? "selected" : "") +
        '" type="button" data-assignment="' + esc(item.assignment_id) + '"><span class="assignment-initial">' +
        esc(item.title.slice(0, 1)) + '</span><span class="assignment-copy"><strong>' + esc(item.title) + '</strong><small>' +
        esc(item.team_name) + ' · ' + esc(trackName(item.track_id)) + '</small></span>' +
        '<span class="status-chip ' + (done ? "done" : "wait") + '">' + (done ? "SCORED" : "TO REVIEW") + '</span></button>';
    }).join("");
    var rubric = state.event.rubric || [];
    var editor = selected ? '<div class="panel"><div class="panel-head"><div><h3>' + esc(selected.title) +
      '</h3><p>' + esc(selected.team_name) + ' · ' + esc(trackName(selected.track_id)) + '</p></div><span class="pill pill-accent">PRIVATE BALLOT</span></div>' +
      '<div class="panel-pad"><p style="margin-top:0;color:#65685f;font-size:11px;line-height:1.7">' +
      esc(selected.description || selected.tagline || "No project description has been provided.") + '</p>' +
      '<div class="detail-links">' + safeLink(selected.repo_url, "Repository") + safeLink(selected.live_url, "Live demo") +
      safeLink(selected.demo_url, "Demo video") + '</div><div style="margin-top:14px">' +
      rubric.map(function (criterion) {
        var info = criterionInfo[criterion.key] || [criterion.label, "Score this criterion from 1 to 5."];
        return '<div class="rubric-row"><div><label>' + esc(criterion.label) + '</label><small>' +
          esc(info[1]) + ' · weight ' + Math.round(Number(criterion.weight) * 100) + '%</small></div><div class="score-options">' +
          scoreButton(criterion.key,selected.criteria && selected.criteria[criterion.key]) + '</div></div>';
      }).join("") + '</div><div class="form-field" style="margin-top:15px"><label for="judge-comment">Private feedback <span>visible to organizers</span></label>' +
      '<textarea id="judge-comment" class="text-control" style="min-height:92px" placeholder="What stood out? What should the team try next?">' +
      esc(selected.comment || "") + '</textarea></div><div class="form-actions"><p>Scores are private to you until the organizer closes review.</p>' +
      '<button class="button button-primary" data-action="save-score" data-assignment="' + esc(selected.assignment_id) + '">Save review →</button></div></div></div>' :
      '<div class="empty-state"><strong>Your queue is clear</strong>There are no assigned projects yet.</div>';
    var doneCount = state.assignments.filter(function (item) { return item.criteria && Object.keys(item.criteria).length; }).length;
    node.innerHTML = '<div class="page-heading"><div><h1>Judge desk</h1><p>Independent reviews, private by default. Take a moment with each build and leave feedback teams can act on.</p></div>' +
      '<span class="pill pill-accent">' + esc(state.user.name) + ' · JUDGE</span></div>' +
      '<div class="metric-grid"><div class="metric-card"><span>Assigned reviews</span><strong>' + state.assignments.length + '</strong><small>In your current queue</small></div>' +
      '<div class="metric-card"><span>Completed</span><strong>' + doneCount + '</strong><small>Saved ballots</small></div>' +
      '<div class="metric-card"><span>Remaining</span><strong>' + Math.max(0,state.assignments.length-doneCount) + '</strong><small>Ready when you are</small></div>' +
      '<div class="metric-card"><span>Event rubric</span><strong>' + rubric.length + '</strong><small>Weighted criteria</small></div></div>' +
      '<div class="split-layout"><section><div class="section-caption"><h3>Your review queue</h3><span>' + state.assignments.length + ' ASSIGNED</span></div>' +
      '<div class="assignment-list">' + (queue || '<div class="empty-state"><strong>No assignments yet</strong>Ask the organizer to generate review batches.</div>') +
      '</div></section><section><div class="section-caption"><h3>Review project</h3><span>1—5 SCORE</span></div>' + editor + '</section></div>';
  }
  function trackName(trackId) {
    var track = state.tracks.find(function (item) { return item.id === trackId; });
    return track ? track.name : trackId;
  }
  function eventInput(name, label, value) {
    return '<div class="form-field"><label>' + esc(label) + '</label><input class="field-control" type="datetime-local" name="' +
      esc(name) + '" value="' + esc(inputDate(value)) + '"></div>';
  }
  function renderOrganizer() {
    var node = document.getElementById("view-organizer");
    if (!state.user || !["organizer","admin"].includes(state.user.role)) {
      node.innerHTML = '<div class="page-heading"><div><h1>Event control</h1><p>Operations, assignments, audit and final results.</p></div></div>' +
        '<div class="empty-state"><strong>Organizer access required</strong>Sign in with an organizer account to control this event.' +
        '<p><button class="button button-dark" data-demo="organizer">Sign in as a demo organizer</button></p></div>';
      return;
    }
    var progress = state.metrics || {};
    var results = state.organizerResults || [];
    var resultRows = results.slice(0,10).map(function (item,index) {
      return '<tr><td><span class="score-pill">#' + (index+1) + '</span></td><td><strong>' + esc(item.title) +
        '</strong></td><td>' + esc(trackName(item.track_id)) + '</td><td>' +
        (item.raw_score == null ? "—" : Number(item.raw_score).toFixed(2)) + '</td><td><strong>' +
        (item.normalized_score == null ? "—" : Number(item.normalized_score).toFixed(2)) + '</strong></td><td>' +
        item.review_count + '</td></tr>';
    }).join("");
    var audits = state.audit.slice(0,8).map(function (item) {
      return '<div class="audit-row"><time>' + esc(item.created_at.replace("T"," ").replace("Z"," UTC")) +
        '</time><div><strong>' + esc(item.action) + '</strong><small>' + esc(item.entity_type) + ' ' +
        esc(item.entity_id) + ' · by ' + esc(item.actor_id || "system") + '</small></div><span class="hash-mark">' +
        esc(item.entry_hash.slice(0,12)) + '</span></div>';
    }).join("");
    node.innerHTML = '<div class="page-heading"><div><h1>Event control</h1><p>Assignment progress, trusted results and the history behind every decision.</p></div>' +
      '<div class="toolbar-actions"><button class="button button-ghost button-small" data-action="open-events">Manage event</button>' +
      '<button class="button button-primary button-small" data-action="new-event">＋ New event</button></div></div>' +
      '<div class="metric-grid"><div class="metric-card"><span>Projects in review</span><strong>' + (progress.projects || 0) +
      '</strong><small>Submitted entries</small></div><div class="metric-card"><span>Reviews complete</span><strong>' +
      (progress.reviews_completed || 0) + '<small style="display:inline"> / ' + (progress.assignments || 0) + '</small></strong><small>Across all judges</small></div>' +
      '<div class="metric-card"><span>Judges started</span><strong>' + (progress.judges_started || 0) + '</strong><small>Of ' +
      (progress.judges_assigned || 0) + ' assigned</small></div><div class="metric-card"><span>Completion</span><strong>' +
      (progress.completion_percent || 0) + '<small style="display:inline">%</small></strong><div class="progress-track" style="margin-top:8px"><i style="width:' +
      (progress.completion_percent || 0) + '%"></i></div></div></div>' +
      '<div class="split-layout"><section><div class="panel"><div class="panel-head"><div><h3>Judging progress</h3><p>Review work is private between each judge and the organizer.</p></div>' +
      '<button class="button button-dark button-small" data-action="auto-assign">Generate assignments</button></div><div class="panel-pad">' +
      '<div class="notice-line">The assignment algorithm only considers judges assigned to each project track and balances total workloads.</div>' +
      '<div class="form-grid" style="margin-top:14px"><div class="form-field"><label>Reviews per project</label><select id="reviews-count" class="select-control"><option value="2">2 independent reviews</option><option value="3" selected>3 independent reviews</option><option value="4">4 independent reviews</option></select></div>' +
      '<div class="form-field"><label>Review completion</label><div style="padding-top:8px"><strong style="font:14px ui-monospace,monospace">' +
      (progress.reviews_remaining || 0) + '</strong><span style="color:#9a9c93;font-size:9px"> reviews remain</span></div></div></div></div></div>' +
      '<div class="panel" style="margin-top:14px"><div class="panel-head"><div><h3>Normalized leaderboard</h3><p>Judge severity is calibrated per criterion with shrinkage.</p></div>' +
      '<div class="toolbar-actions"><a class="button button-ghost button-small" href="/api/export.csv?kind=results">Export results</a>' +
      '<button class="button button-primary button-small" data-action="publish-results">Publish results</button></div></div>' +
      '<div class="table-wrap"><table class="data-table"><thead><tr><th>Rank</th><th>Project</th><th>Track</th><th>Raw</th><th>Adjusted</th><th>Reviews</th></tr></thead><tbody>' +
      (resultRows || '<tr><td colspan="6">No project scores are available yet.</td></tr>') +
      '</tbody></table></div><div class="panel-pad"><p class="form-help">Normalization is a judge-level z adjustment per criterion, centered on the event mean, reliability-shrunk by n/(n+5), then clipped to the 1–5 scale. Raw and adjusted score exports are retained.</p>' +
      '<button class="button button-ghost button-small" data-action="normalization-proof">View normalization proof</button><span id="normalization-note"></span></div></div></section>' +
      '<aside><section class="panel"><div class="panel-head"><div><h3>Operations</h3><p>Portable copies and logs</p></div></div><div class="panel-pad"><div class="assignment-list">' +
      '<a class="assignment-row" href="/api/export.csv?kind=projects"><span class="assignment-initial">↓</span><span class="assignment-copy"><strong>Export submissions</strong><small>CSV · project register</small></span></a>' +
      '<a class="assignment-row" href="/api/export.csv?kind=assignments"><span class="assignment-initial">↓</span><span class="assignment-copy"><strong>Export assignments</strong><small>CSV · judge progress</small></span></a>' +
      '<a class="assignment-row" href="/api/export.csv?kind=scores"><span class="assignment-initial">↓</span><span class="assignment-copy"><strong>Export review scores</strong><small>CSV · raw ballots</small></span></a>' +
      '<a class="assignment-row" href="/api/export.json"><span class="assignment-initial">↗</span><span class="assignment-copy"><strong>Full event backup</strong><small>JSON · importable offline</small></span></a>' +
      '<label class="assignment-row" style="cursor:pointer"><span class="assignment-initial">↑</span><span class="assignment-copy"><strong>Restore event backup</strong><small>Import a Fieldnote JSON archive</small></span><input id="event-import" type="file" accept=".json,application/json" hidden></label>' +
      '<a class="assignment-row" href="/api/verify/audit" target="_blank"><span class="assignment-initial">✓</span><span class="assignment-copy"><strong>Verify audit chain</strong><small>Public hash-chain integrity check</small></span></a>' +
      '<a class="assignment-row" href="/openapi.json" target="_blank"><span class="assignment-initial">{} </span><span class="assignment-copy"><strong>OpenAPI reference</strong><small>REST endpoints in JSON</small></span></a>' +
      '</div></div></section><section class="panel" style="margin-top:14px"><div class="panel-head"><div><h3>Invite a judge</h3><p>Track-scoped reviewer accounts</p></div></div><div class="panel-pad">' +
      '<form data-form="judge" class="form-grid"><div class="form-field full"><label>Name</label><input name="name" class="field-control" required></div>' +
      '<div class="form-field full"><label>Email</label><input name="email" type="email" class="field-control" required></div>' +
      '<div class="form-field full"><label>Assigned tracks</label><div class="choice-row">' +
      state.tracks.map(function(track){return '<label class="choice"><input type="checkbox" name="tracks" value="' +
        esc(track.id) + '">' + esc(track.name) + '</label>';}).join("") + '</div></div>' +
      '<div class="form-field full"><button class="button button-dark button-small" type="submit">Create judge account</button></div></form>' +
      '<p class="form-help">A one-time temporary password appears after creation. Share it with the reviewer over a private channel.</p>' +
      '<div class="section-caption"><h3>Judge roster</h3><span>' + state.judges.length + ' ACCOUNTS</span></div>' +
      '<div class="assignment-list">' + state.judges.slice(0,8).map(function(judge){return '<div class="assignment-row">' +
        '<span class="assignment-initial">' + esc(initials(judge.name)) + '</span><span class="assignment-copy"><strong>' +
        esc(judge.name) + '</strong><small>' + esc(judge.email) + ' · ' + judge.assigned + ' assigned</small></span></div>';}).join("") +
      '</div></div></section><section class="panel" style="margin-top:14px"><div class="panel-head"><div><h3>Recent event history</h3><p>Append-only and hash-linked activity</p></div></div><div class="panel-pad"><div class="audit-list">' +
      (audits || '<div class="empty-state">Nothing has happened yet.</div>') + '</div></div></section></aside></div>';
  }
  function trackName(trackId) {
    var track = state.tracks.find(function (item) { return item.id === trackId; });
    return track ? track.name : trackId;
  }
  function loadJudging() {
    if (!state.user || !["judge","organizer","admin"].includes(state.user.role)) return Promise.resolve();
    return api("/api/judge/assignments").then(function (data) {
      state.assignments = data.assignments || [];
      if (!state.assignments.some(function (item) { return item.assignment_id === state.selectedAssignment; })) {
        state.selectedAssignment = "";
      }
    });
  }
  function loadOrganizer() {
    if (!state.user || !["organizer","admin"].includes(state.user.role)) return Promise.resolve();
    return Promise.all([
      api("/api/organizer/progress"), api("/api/organizer/results"), api("/api/audit"),
      api("/api/organizer/judges")
    ]).then(function (values) {
      state.metrics = values[0];
      state.organizerResults = values[1].results || [];
      state.audit = values[2].entries || [];
      state.judges = values[3].judges || [];
    }).catch(function (error) { notice(error.message, true); });
  }
  function openAuth(mode) {
    state.authMode = mode || "login";
    renderAuth();
    document.getElementById("auth-dialog").showModal();
  }
  function renderAuth() {
    var isRegister = state.authMode === "register";
    document.getElementById("auth-content").innerHTML =
      '<span class="eyebrow">FIELDNOTE ACCESS</span><h2 style="margin-top:9px">' +
      (isRegister ? "Create your account" : "Welcome back") + '</h2><p>' +
      (isRegister ? "Join the event as a participant. You can build a team and submit once you sign in." :
        "Use your event account or try a seeded demo role.") + '</p>' +
      '<form id="auth-form" data-form="auth" class="form-grid" style="margin-top:17px">' +
      (isRegister ? '<div class="form-field full"><label>Your name</label><input class="field-control" name="name" required maxlength="100" placeholder="Ada Lovelace"></div>' : "") +
      '<div class="form-field full"><label>Email</label><input class="field-control" name="email" type="email" required autocomplete="username" placeholder="you@example.org"></div>' +
      '<div class="form-field full"><label>Password</label><input class="field-control" name="password" type="password" required minlength="' +
      (isRegister ? "10" : "1") + '" autocomplete="' + (isRegister ? "new-password" : "current-password") + '" placeholder="' +
      (isRegister ? "At least 10 characters" : "Your password") + '"></div>' +
      '<div id="auth-error" class="inline-error full"></div><div class="form-field full"><button class="button button-dark" type="submit" style="width:100%">' +
      (isRegister ? "Create participant account" : "Sign in") + ' →</button></div></form>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin:12px 0 5px"><span class="eyebrow">SEE THE SEEDED DEMO</span>' +
      '<button class="card-open" data-auth-mode="' + (isRegister ? "login" : "register") + '" type="button">' +
      (isRegister ? "Already registered? Sign in" : "Create an account") + '</button></div>' +
      '<div class="demo-account"><strong>Organizer</strong><small>organizer@dogfood.local · raptors2026</small><button class="button button-ghost button-small" data-demo="organizer">Use</button></div>' +
      '<div class="demo-account"><strong>Judge · Tomas</strong><small>tomas.varga@example.org · demo-pass</small><button class="button button-ghost button-small" data-demo="judge">Use</button></div>' +
      '<div class="demo-account"><strong>Participant</strong><small>participant@example.org · demo-pass</small><button class="button button-ghost button-small" data-demo="participant">Use</button></div>';
  }
  function openEvents() {
    var current = state.event || {};
    var canManage = state.user && (state.user.role === "organizer" || state.user.role === "admin");
    var choices = state.events.map(function (event) {
      return (canManage ? '<button type="button" class="assignment-row" data-select-event="' + esc(event.id) + '">' : '<div class="assignment-row">') + '<span class="assignment-initial">E</span>' +
        '<span class="assignment-copy"><strong>' + esc(event.name) + '</strong><small>' + esc(event.id) + '</small></span>' +
        (current.id === event.id ? '<span class="pill pill-accent">ACTIVE</span>' : "") + (canManage ? '</button>' : '</div>');
    }).join("");
    document.getElementById("event-content").innerHTML =
      '<span class="eyebrow">EVENT WORKSPACE</span><h2 style="margin-top:9px">Your events</h2>' +
      '<p>' + (canManage ? "Switch the active workspace or adjust event dates, voting windows and project tracks." : "Event schedule and workspace details.") + '</p>' +
      '<div class="assignment-list" style="margin:15px 0 20px">' + choices + '</div>' +
      (!canManage ? '<div class="panel-pad" style="border:1px solid #ecece7;border-radius:8px"><strong>' + esc(current.name || "Event") +
        '</strong><p class="form-help">Submissions close ' + esc(titleDate(current.submissions_close)) + '. Contact an organizer to change event settings.</p></div>' :
      '<form id="event-settings-form" data-form="event-settings" class="form-grid">' +
      '<div class="form-field full"><label>Event name</label><input class="field-control" name="name" required value="' + esc(current.name) + '"></div>' +
      '<div class="form-field full"><label>Short description</label><textarea class="text-control" name="description">' + esc(current.description) + '</textarea></div>' +
      eventInput("opens_at","Opens (UTC)",current.opens_at) +
      eventInput("submissions_close","Submissions close (UTC)",current.submissions_close) +
      eventInput("judging_close","Judging close (UTC)",current.judging_close) +
      eventInput("voting_open","Community voting opens (UTC)",current.voting_open) +
      eventInput("voting_close","Community voting closes (UTC)",current.voting_close) +
      '<div class="form-field"><label>Community voting access</label><select name="voting_mode" class="select-control">' +
      '<option value="open" ' + (current.voting_mode === "open" ? "selected" : "") + '>Open link</option>' +
      '<option value="email" ' + (current.voting_mode === "email" ? "selected" : "") + '>Email account</option>' +
      '<option value="authenticated" ' + (current.voting_mode === "authenticated" ? "selected" : "") + '>Signed in</option></select></div>' +
      '<div class="form-field full"><label>Tracks <span>one per line</span></label><textarea name="tracks" class="text-control" style="min-height:100px">' +
      esc((current.tracks || []).map(function (item) { return item.id + "|" + item.name; }).join("\n")) +
      '</textarea><p class="form-help">Keep each track ID stable when renaming a track, for example trk_01|Developer tools.</p></div>' +
      '<div class="form-field full"><label>Weighted judging rubric <span>key|label|weight per line</span></label><textarea name="rubric" class="text-control" style="min-height:100px">' +
      esc((current.rubric || []).map(function(item){return item.key+"|"+item.label+"|"+item.weight;}).join("\n")) +
      '</textarea><p class="form-help">Weights are normalized automatically. Every criterion uses the 1–5 scale.</p></div>' +
      '<div class="form-field full"><label>Prizes <span>place|amount|label per line</span></label><textarea name="prizes" class="text-control">' +
      esc((current.prizes || []).map(function(item){return (item.place||"")+"|"+(item.amount||"")+"|"+(item.label||"");}).join("\n")) +
      '</textarea></div>' +
      '<div class="form-field full"><label>Custom submission questions <span>key|question|required per line</span></label><textarea name="questions" class="text-control">' +
      esc((current.questions || []).map(function(item){return item.key+"|"+item.label+"|"+(item.required?"required":"optional");}).join("\n")) +
      '</textarea></div>' +
      '<div class="form-field full"><button class="button button-primary" type="submit">Save event settings →</button></div></form>');
    document.getElementById("event-dialog").showModal();
  }
  function openNewEvent() {
    document.getElementById("event-content").innerHTML =
      '<span class="eyebrow">EVENT SETUP</span><h2 style="margin-top:9px">Create an event</h2><p>Set the dates, tracks and public description. A starter weighted rubric is created automatically.</p>' +
      '<form id="new-event-form" data-form="new-event" class="form-grid" style="margin-top:16px">' +
      '<div class="form-field full"><label>Event name</label><input name="name" class="field-control" required maxlength="150" placeholder="Winter build sprint"></div>' +
      '<div class="form-field full"><label>Event description</label><textarea name="description" class="text-control"></textarea></div>' +
      eventInput("opens_at","Opens (UTC)",new Date().toISOString()) +
      eventInput("submissions_close","Submission deadline (UTC)",new Date(Date.now()+7*86400000).toISOString()) +
      '<div class="form-field"><label>Community voting access</label><select name="voting_mode" class="select-control"><option value="authenticated">Signed in</option><option value="open">Open link</option><option value="email">Email account</option></select></div>' +
      eventInput("voting_open","Voting opens (UTC)","") +
      eventInput("voting_close","Voting closes (UTC)","") +
      '<div class="form-field full"><label>Tracks <span>one per line</span></label><textarea name="tracks" class="text-control" required placeholder="Developer tools&#10;Accessibility&#10;Climate"></textarea></div>' +
      '<div class="form-field full"><label>Prizes <span>place|amount|label per line</span></label><textarea name="prizes" class="text-control" placeholder="1st|800|Grand prize&#10;2nd|500|Runner up"></textarea></div>' +
      '<div class="form-field full"><label>Custom questions <span>key|question|required per line</span></label><textarea name="questions" class="text-control" placeholder="challenge|What did you learn?|required"></textarea></div>' +
      '<div class="form-field full"><button class="button button-primary" type="submit">Create and open event →</button></div></form>';
    document.getElementById("event-dialog").showModal();
  }
  function openProject(id) {
    api("/api/projects/" + encodeURIComponent(id)).then(function (data) {
      var project = data.project;
      state.projectDetail = project;
      document.getElementById("project-content").innerHTML =
        '<div class="project-detail-head"><div><span class="track-chip">' + esc(project.track) + '</span><h2>' +
        esc(project.title) + '</h2><p>by ' + esc(project.team_name) + ' · ' + esc(project.id) + '</p></div>' +
        '<span class="pill pill-accent">SUBMITTED</span></div><p style="margin:14px 0 0;color:#66705b;font-size:12px">' +
        esc(project.tagline || "") + '</p><div class="project-detail-body">' + esc(project.description || "This project has not added a longer description yet.") +
        '</div><div class="tag-row" style="margin-top:14px">' + (project.tech_tags || []).map(function (tag) {
          return '<span class="tech-tag">' + esc(tag) + '</span>';
        }).join("") + '</div><div class="detail-links">' + safeLink(project.repo_url,"Repository") +
        safeLink(project.live_url,"Live demo") + safeLink(project.demo_url,"Demo video") +
        (project.gallery || []).map(function (url,index) { return safeLink(url,"Image " + (index+1)); }).join("") +
        '</div><section style="margin-top:22px;padding-top:16px;border-top:1px solid #ebebe4"><div class="section-caption" style="margin:0"><h3>Community notes</h3>' +
        '<span>' + project.comments.length + ' COMMENTS</span></div><div class="comment-list">' +
        project.comments.map(function (comment) {
          return '<div class="comment-item"><strong>' + esc(comment.author) + '</strong><p>' + esc(comment.body) + '</p></div>';
        }).join("") + '</div>' +
        (state.user ? '<form data-form="comment" class="form-grid" style="margin-top:12px"><input type="hidden" name="project_id" value="' + esc(project.id) + '">' +
          '<div class="form-field full"><label>Add a constructive note</label><textarea class="text-control" name="body" maxlength="1000" required placeholder="What did you like? What question would you ask the team?"></textarea></div>' +
          '<div class="form-field full"><button class="button button-dark button-small" type="submit">Add comment</button></div></form>' :
          '<p class="form-help" style="margin-top:13px">Sign in to add a community note.</p>') +
        '</section>';
      document.getElementById("project-dialog").showModal();
    }).catch(function (error) { notice(error.message,true); });
  }
  function demoLogin(role) {
    var account = role === "organizer" ?
      ["organizer@dogfood.local","raptors2026"] :
      role === "judge" ? ["tomas.varga@example.org","demo-pass"] :
      ["participant@example.org","demo-pass"];
    api("/api/auth/login",{method:"POST",body:{email:account[0],password:account[1]}}).then(function () {
      document.getElementById("auth-dialog").close();
      notice("Signed in as the demo " + role + ".");
      refresh().then(function () {
        if (state.pendingInvite) acceptInvite();
        if (state.view === "judging") loadJudging().then(renderJudging);
        if (state.view === "organizer") loadOrganizer().then(renderOrganizer);
      });
    }).catch(function (error) { notice(error.message,true); });
  }
  function submitProjectForm(form,submitter) {
    if (state.event.submission_open === false) {
      notice("This event is closed for submissions.",true);
      return;
    }
      var data=new FormData(form);var tags=String(data.get("tech_tags")||"").split(",").map(function(x){return x.trim();}).filter(Boolean);
    var answers={};
    (state.event.questions||[]).forEach(function(question){answers[question.key]=data.get("answer_"+question.key)||"";});
    var gallery=String(data.get("gallery")||"").split(/\r?\n/).map(function(x){return x.trim();}).filter(Boolean);
    var body={
      title:data.get("title"),track_id:data.get("track_id"),tagline:data.get("tagline"),
      description:data.get("description"),repo_url:data.get("repo_url"),live_url:data.get("live_url"),
      demo_url:data.get("demo_url"),thumbnail_url:data.get("thumbnail_url"),tech_tags:tags,
      gallery:gallery,answers:answers,
      draft:submitter && submitter.getAttribute("data-status")==="draft"
    };
    var endpoint=state.editingProject?"/api/projects/"+encodeURIComponent(state.editingProject.id):"/api/projects";
    api(endpoint,{method:state.editingProject?"PUT":"POST",body:body}).then(function(data){
      notice(data.project.status==="draft"?"Draft saved.":"Project entry saved.");
      state.editingProject=null;
      loadMine().then(function(){renderSubmit();});
      refresh();
    }).catch(function(error){notice(error.message,true);});
  }
  function acceptInvite() {
    if (!state.pendingInvite || !state.user) return;
    api("/api/invites/"+encodeURIComponent(state.pendingInvite)+"/accept",{method:"POST",body:{}}).then(function(){
      state.pendingInvite="";
      history.replaceState({}, "", "/");
      notice("You joined the team.");
      loadTeams().then(function(){setNav("submit");});
    }).catch(function(error){notice(error.message,true);});
  }
  function clickHandler(event) {
    var target=event.target.closest("button,a,label");
    if (!target) return;
    if (target.matches("[data-view]")) {
      event.preventDefault();
      var view=target.getAttribute("data-view");
      if ((view==="submit"||view==="judging"||view==="organizer") && !state.user) {
        openAuth("login");notice("Sign in to open this workspace.");return;
      }
      if (view==="submit"&&state.user.role!=="participant") {notice("Only participant accounts can submit.",true);return;}
      setNav(view);
      if (view==="judging") loadJudging().then(renderJudging).catch(function(e){notice(e.message,true);});
      if (view==="organizer") loadOrganizer().then(renderOrganizer);
      if (view==="submit") {state.mine=[];state.teams=[];loadMine();loadTeams();}
      return;
    }
    if (target.matches("#sign-in,#profile-button")) {
      event.preventDefault();
      if (!state.user) openAuth("login");
      else if (target.id==="sign-in" || target.id==="profile-button") {
        api("/api/auth/logout",{method:"POST",body:{}}).then(function(){
          applyUser(null);notice("You have signed out.");refresh().then(function(){setNav("gallery");});
        }).catch(function(error){notice(error.message,true);});
      }
      return;
    }
    if (target.matches("[data-demo]")) { event.preventDefault();demoLogin(target.getAttribute("data-demo"));return; }
    if (target.matches("[data-auth-mode]")) {state.authMode=target.getAttribute("data-auth-mode");renderAuth();return;}
    if (target.matches("[data-open-project]")) {event.preventDefault();openProject(target.getAttribute("data-open-project"));return;}
    if (target.matches("[data-edit-project]")) {
      var item=state.mine.find(function(project){return project.id===target.getAttribute("data-edit-project");});
      if(item){state.editingProject=item;setNav("submit");}
      return;
    }
    if (target.matches("[data-invite-team]")) {
      var email=prompt("Invite teammate by email (optional):","");
      if(email===null)return;
      api("/api/teams/"+encodeURIComponent(target.getAttribute("data-invite-team"))+"/invites",
          {method:"POST",body:{email:email}}).then(function(data){
        var link=location.origin+data.invite_url;
        if(navigator.clipboard) navigator.clipboard.writeText(link).catch(function(){});
        notice("Invite link copied: "+link);
      }).catch(function(error){notice(error.message,true);});
      return;
    }
    if (target.matches("[data-assignment]")) {
      state.selectedAssignment=target.getAttribute("data-assignment");renderJudging();return;
    }
    if (target.matches("[data-score]")) {
      var criterion=target.getAttribute("data-score"),value=target.getAttribute("data-value");
      var row=target.closest(".rubric-row");
      row.querySelectorAll("[data-score]").forEach(function(button){
        button.classList.toggle("chosen",button.getAttribute("data-value")===value);
      });
      target.setAttribute("aria-pressed","true");
      return;
    }
    if (target.matches("[data-action='save-score']")) {
      var assignment=state.assignments.find(function(item){return item.assignment_id===target.getAttribute("data-assignment");});
      if(!assignment)return;
      var criteria={};
      document.querySelectorAll("#view-judging .rubric-row").forEach(function(row){
        var chosen=row.querySelector(".score-option.chosen");
        if(chosen)criteria[chosen.getAttribute("data-score")]=Number(chosen.getAttribute("data-value"));
      });
      if(Object.keys(criteria).length!==(state.event.rubric||[]).length){notice("Score each rubric criterion before saving.",true);return;}
      api("/api/judge/scores",{method:"POST",body:{project_id:assignment.id?assignment.id:assignment.id,criteria:criteria,
          comment:document.getElementById("judge-comment").value}}).then(function(){
        notice("Review saved securely.");
        loadJudging().then(renderJudging);
      }).catch(function(error){
        // The assignment identifier is not the project identifier. Resolve it from the selected item.
        if(error.status===403) notice(error.message,true); else notice(error.message,true);
      });
      return;
    }
    if (target.matches("[data-action='auto-assign']")) {
      var count=Number(document.getElementById("reviews-count").value||3);
      api("/api/organizer/assignments/auto",{method:"POST",body:{reviews_per_project:count}})
        .then(function(data){state.metrics=data.progress;notice(data.added+" new reviews assigned.");loadOrganizer().then(renderOrganizer);})
        .catch(function(error){notice(error.message,true);});return;
    }
    if (target.matches("[data-action='publish-results']")) {
      if(!confirm("Publish the weighted event results to the public gallery?"))return;
      api("/api/results/publish",{method:"POST",body:{}}).then(function(){notice("Results are now public.");refresh();})
        .catch(function(error){notice(error.message,true);});return;
    }
    if (target.matches("[data-action='normalization-proof']")) {
      api("/api/organizer/results").then(function(data){
        var proof=data.normalization||{},lines=[];
        Object.keys(proof).forEach(function(key){
          var item=proof[key];lines.push(key+": "+item.ratings+" scores · event μ "+item.overall_mean+
            " · event σ "+item.overall_sd+" · "+item.judge_count+" judges");
        });
        var node=document.getElementById("normalization-note");
        node.textContent=lines.join(" | ");node.className="form-help";
      }).catch(function(error){notice(error.message,true);});return;
    }
    if (target.matches("[data-action='ballot']")) {
      api("/api/voting/ballot").then(function(data){state.ballot=data;renderGallery();})
        .catch(function(error){notice(error.message,true);if(error.status===401)openAuth("login");});return;
    }
    if (target.matches("[data-vote]")) {
      var projectId=target.getAttribute("data-vote");
      var select=document.querySelector('[data-vote-credit="'+CSS.escape(projectId)+'"]');
      var credits=Number(select.value||0);
      if(!credits){notice("Choose a credit amount first.",true);return;}
      api("/api/votes",{method:"POST",body:{project_id:projectId,credits:credits}})
        .then(function(){notice("Your vote was recorded.");return api("/api/voting/ballot");})
        .then(function(data){state.ballot=data;renderGallery();})
        .catch(function(error){notice(error.message,true);});return;
    }
    if (target.matches("[data-action='open-events']")) {openEvents();return;}
    if (target.matches("[data-action='new-event']")) {openNewEvent();return;}
    if (target.matches("[data-select-event]")) {
      api("/api/events/select",{method:"POST",body:{event_id:target.getAttribute("data-select-event")}})
        .then(function(){document.getElementById("event-dialog").close();state.ballot=null;refresh();notice("Event workspace changed.");})
        .catch(function(error){notice(error.message,true);});return;
    }
    if (target.matches("[data-action='cancel-edit']")) {state.editingProject=null;renderSubmit();return;}
  }
  function submitHandler(event) {
    var form=event.target.closest("form[data-form]");
    if(!form)return;
    event.preventDefault();
    var type=form.getAttribute("data-form");
    if(type==="auth"){
      var data=new FormData(form);
      var body={email:data.get("email"),password:data.get("password")};
      var register=state.authMode==="register";
      if(register){body.name=data.get("name");}
      api(register?"/api/auth/register":"/api/auth/login",{method:"POST",body:body}).then(function(){
        document.getElementById("auth-dialog").close();notice(register?"Participant account created.":"You are signed in.");
        refresh().then(function(){
          if(state.pendingInvite)acceptInvite();
          if(state.view==="submit"){state.mine=[];state.teams=[];loadMine();loadTeams();}
          if(state.view==="judging")loadJudging().then(renderJudging);
          if(state.view==="organizer")loadOrganizer().then(renderOrganizer);
        });
      }).catch(function(error){
        var target=document.getElementById("auth-error");if(target)target.textContent=error.message;
      });
      return;
    }
    if(type==="project"){submitProjectForm(form,event.submitter);return;}
    if(type==="team"){
      var teamData=new FormData(form);
      api("/api/teams",{method:"POST",body:{name:teamData.get("name")}}).then(function(data){
        notice("Team created. Invite code: "+data.invite_code);state.teams=[];loadTeams();
      }).catch(function(error){notice(error.message,true);});return;
    }
    if(type==="judge"){
      var judgeData=new FormData(form);
      var tracks=judgeData.getAll("tracks");
      if(!tracks.length){notice("Choose at least one track for this reviewer.",true);return;}
      api("/api/judges",{method:"POST",body:{name:judgeData.get("name"),email:judgeData.get("email"),tracks:tracks}})
        .then(function(data){
          window.alert("Temporary password for "+data.judge.email+": "+data.temporary_password+
            "\n\nShare it privately. It is shown only once.");
          form.reset();return loadOrganizer();
        }).then(renderOrganizer).catch(function(error){notice(error.message,true);});
      return;
    }
    if(type==="comment"){
      var commentData=new FormData(form);
      api("/api/comments",{method:"POST",body:{project_id:commentData.get("project_id"),body:commentData.get("body")}})
        .then(function(){notice("Community note added.");openProject(state.projectDetail.id);})
        .catch(function(error){notice(error.message,true);});return;
    }
    if(type==="event-settings"){
      var eventData=new FormData(form);var trackLines=String(eventData.get("tracks")||"").split(/\r?\n/).filter(Boolean);
      var tracks=trackLines.map(function(line){
        var split=line.indexOf("|");
        if(split<0)return {id:"trk_"+line.toLowerCase().replace(/[^a-z0-9]+/g,"_"),name:line.trim()};
        return {id:line.slice(0,split).trim(),name:line.slice(split+1).trim()};
      });
      var rubric=String(eventData.get("rubric")||"").split(/\r?\n/).filter(Boolean).map(function(line,index){
        var parts=line.split("|");return {key:(parts[0]||("criterion_"+index)).trim(),label:(parts[1]||parts[0]||"Criterion").trim(),weight:Number(parts[2]||1)};
      });
      var prizes=String(eventData.get("prizes")||"").split(/\r?\n/).filter(Boolean).map(function(line,index){
        var parts=line.split("|");return {place:(parts[0]||String(index+1)).trim(),amount:Number(parts[1]||0),label:(parts[2]||"Prize").trim()};
      });
      var questions=String(eventData.get("questions")||"").split(/\r?\n/).filter(Boolean).map(function(line,index){
        var parts=line.split("|");return {key:(parts[0]||("question_"+index)).trim(),label:(parts[1]||parts[0]||"Question").trim(),
          type:"text",required:String(parts[2]||"").trim().toLowerCase()==="required"};
      });
      var body={name:eventData.get("name"),description:eventData.get("description"),
        opens_at:utcValue(eventData.get("opens_at")),submissions_close:utcValue(eventData.get("submissions_close")),
        judging_close:utcValue(eventData.get("judging_close")),voting_open:utcValue(eventData.get("voting_open")),
        voting_close:utcValue(eventData.get("voting_close")),voting_mode:eventData.get("voting_mode"),
        tracks:tracks,rubric:rubric,prizes:prizes,questions:questions};
      api("/api/events/"+encodeURIComponent(state.event.id),{method:"PATCH",body:body}).then(function(){
        document.getElementById("event-dialog").close();notice("Event settings saved.");refresh();
      }).catch(function(error){notice(error.message,true);});return;
    }
    if(type==="new-event"){
      var newData=new FormData(form);
      var tracks=String(newData.get("tracks")||"").split(/\r?\n/).map(function(line){return line.trim();}).filter(Boolean);
      var prizes=String(newData.get("prizes")||"").split(/\r?\n/).filter(Boolean).map(function(line,index){
        var parts=line.split("|");return {place:(parts[0]||String(index+1)).trim(),amount:Number(parts[1]||0),label:(parts[2]||"Prize").trim()};
      });
      var questions=String(newData.get("questions")||"").split(/\r?\n/).filter(Boolean).map(function(line,index){
        var parts=line.split("|");return {key:(parts[0]||("question_"+index)).trim(),label:(parts[1]||parts[0]||"Question").trim(),
          type:"text",required:String(parts[2]||"").trim().toLowerCase()==="required"};
      });
      api("/api/events",{method:"POST",body:{name:newData.get("name"),description:newData.get("description"),
        opens_at:utcValue(newData.get("opens_at")),submissions_close:utcValue(newData.get("submissions_close")),
        voting_open:utcValue(newData.get("voting_open")),voting_close:utcValue(newData.get("voting_close")),
        voting_mode:newData.get("voting_mode"),tracks:tracks,prizes:prizes,questions:questions}}).then(function(){
          document.getElementById("event-dialog").close();state.ballot=null;notice("Event created and selected.");refresh();
        }).catch(function(error){notice(error.message,true);});return;
    }
  }
  function changeHandler(event) {
    if(event.target.id==="event-import"&&event.target.files&&event.target.files[0]){
      var file=event.target.files[0];
      file.text().then(function(content){
        var body=JSON.parse(content);
        return api("/api/export/import",{method:"POST",body:body});
      }).then(function(data){
        notice("Backup restored with "+data.projects+" projects.");refresh();
      }).catch(function(error){notice(error.message||"Could not read that archive.",true);});
    }
  }
  function init() {
    if(document.body.getAttribute("data-embed")==="true")document.body.classList.add("embed-mode");
    document.addEventListener("click",clickHandler);
    document.addEventListener("submit",submitHandler);
    document.addEventListener("change",changeHandler);
    document.getElementById("event-picker").addEventListener("click",openEvents);
    refresh().then(function(){
      if(location.pathname.indexOf("/invite/")===0){
        state.pendingInvite=location.pathname.split("/")[2]||"";
        if(state.user)acceptInvite();else openAuth("login");
      }
      if(location.pathname==="/projects/new"){
        if(!state.user)openAuth("login");else setNav("submit");
      }
      if(state.user&&state.user.role==="participant"){loadMine();loadTeams();}
      if(state.user&&state.user.role==="judge"){loadJudging();}
    });
  }
  init();
}());
