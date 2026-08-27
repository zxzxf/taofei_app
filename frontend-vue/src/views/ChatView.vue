<template>
  <div class="chat-view">
    <div class="chat-sessions" :class="{ collapsed: sidebarCollapsed }" :style="sidebarCollapsed ? {} : { width: sessionsWidth + 'px', flexShrink: 0 }">
      <div class="chat-sessions-head">
        <div class="chat-sessions-head-left">
          <button class="chat-collapse-btn" @click="toggleSidebar" :title="sidebarCollapsed ? '展开会话列表' : '收起会话列表'">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="3" y1="6" x2="21" y2="6"/>
              <line x1="3" y1="12" x2="21" y2="12"/>
              <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <h3 v-if="!sidebarCollapsed">会话列表</h3>
        </div>
        <button v-if="!sidebarCollapsed" class="chat-new-btn" @click="openNewSessionDialog">+ 新对话</button>
      </div>
      <div v-if="!sidebarCollapsed" class="chat-search">
        <input v-model="searchTerm" type="text" placeholder="搜索会话">
      </div>
      <div v-if="!sidebarCollapsed" class="chat-session-list">
        <div
          v-for="s in filteredSessions"
          :key="s.id"
          class="chat-session"
          :class="{ active: s.id === currentId }"
          @click="currentId = s.id"
        >
          <div class="chat-session-info">
            <div class="chat-session-title">
              {{ s.title }}
              <span v-if="s.sending" class="session-running-dot" title="正在思考中"></span>
            </div>
            <div class="chat-session-meta">
              {{ formatTime(s.time) }} · {{ s.messages.length }} 条消息
              <button
                class="session-memory-icon"
                :class="{ on: s.memoryEnabled !== false }"
                :title="s.memoryEnabled !== false ? '会话记忆已开启，点击关闭' : '会话记忆已关闭，点击开启'"
                @click.stop="toggleSessionMemory(s)"
              >🧠</button>
            </div>
            <div v-if="s.skills && s.skills.length || s.modelPresetId" class="chat-session-tags">
              <span v-if="s.modelPresetId && presetNameById(s.modelPresetId)" class="chat-session-model-chip" :title="`本对话使用：${presetNameById(s.modelPresetId)}`">
                🤖 {{ presetNameById(s.modelPresetId) }}
              </span>
              <span v-for="sk in s.skills" :key="sk.id" class="session-skill-chip">{{ sk.icon || '🛠️' }} {{ sk.name }}</span>
            </div>
          </div>
          <button class="chat-session-delete" @click.stop="deleteSession(s.id)">🗑</button>
        </div>
        <div v-if="!filteredSessions.length" style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 12px;">
          暂无会话
        </div>
      </div>
    </div>
    <div v-if="!sidebarCollapsed" class="chat-resizer" :class="{ active: resizing }" @mousedown="startResize"></div>
    <div class="chat-area">
      <div class="chat-area-head">
        <div class="chat-area-head-left">
          <span class="chat-area-title">{{ currentSession?.title || '新对话' }}</span>
          <div v-if="currentSession?.skills?.length" class="chat-area-skills">
            <span v-for="sk in currentSession.skills" :key="sk.id" class="chat-skill-tag">
              {{ sk.icon || '🛠️' }} {{ sk.name }}
            </span>
            <button class="chat-skill-edit" @click="editSkills" title="管理技能">⚙️</button>
          </div>
        </div>
        <div class="chat-area-head-right">
          <!-- 工作空间选择器 -->
          <div class="ws-selector-wrap" v-click-outside="() => wsOpen = false">
            <button class="ws-selector-btn" :class="{ open: wsOpen }" @click="wsOpen = !wsOpen">
              <span class="ws-icon">📁</span>
              <span class="ws-name">{{ currentWorkspaceName }}</span>
              <span class="ws-arrow">▼</span>
            </button>
            <div class="ws-dropdown" :class="{ open: wsOpen }">
              <div class="ws-search">
                <span class="ws-search-icon">🔍</span>
                <input v-model="wsSearch" type="text" placeholder="搜索工作空间" @click.stop />
              </div>
              <div class="ws-list">
                <div
                  v-for="ws in filteredWorkspaces"
                  :key="ws.id"
                  class="ws-item"
                  :class="{ selected: ws.id === currentWorkspaceId }"
                  @click="onWorkspaceChange(ws.id)"
                >
                  <span class="ws-item-icon">📁</span>
                  <div class="ws-item-info">
                    <div class="ws-item-name">{{ ws.name }}</div>
                  </div>
                  <span v-if="ws.id === currentWorkspaceId" class="ws-item-check">✓</span>
                  <div class="ws-item-actions">
                    <button
                      v-if="ws.id !== currentWorkspaceId"
                      title="删除"
                      @click.stop="onDeleteWorkspace(ws.id)"
                    >
                      🗑
                    </button>
                  </div>
                </div>
                <div v-if="filteredWorkspaces.length === 0" class="ws-empty">未找到工作空间</div>
              </div>
              <div class="ws-dropdown-actions">
                <button class="ws-action-open" @click="openLocalFolder">
                  <span></span> 打开本地文件夹
                </button>
                <button class="ws-action-none" @click="onWorkspaceChange(null)">
                  <span></span> 不使用工作空间
                </button>
              </div>
            </div>
          </div>

          <!-- 模型选择器 -->
          <div class="chat-current-model-wrap" :class="{ open: modelMenuOpen }" @click.stop="toggleModelMenu">
            <div class="chat-current-model" :title="currentModelFull">
              <span class="chat-current-model-dot">{{ currentModelInitial }}</span>
              <span class="chat-current-model-text">
                <span class="chat-current-model-name">{{ currentModelName }}</span>
                <span class="chat-current-model-sub">{{ currentModelSub }}</span>
              </span>
              <span class="chat-current-model-arrow">▾</span>
            </div>
            <div class="chat-model-menu" @click.stop>
              <div class="chat-model-menu-header">
                <span>为本对话选择模型</span>
                <button class="chat-model-menu-link" @click.stop="goPresetAdmin">管理预设 →</button>
              </div>
              <div v-if="modelLoading" class="chat-model-menu-empty">加载中…</div>
              <div v-else-if="!presets.length" class="chat-model-menu-empty">
                还没有保存的预设，请到「系统设置」中配置。
              </div>
              <div v-else class="chat-model-menu-list">
                <div
                  v-for="p in presets"
                  :key="p.id"
                  class="chat-model-menu-item"
                  :class="{ active: p.id === currentSessionModelId }"
                  @click="pickModelForSession(p)"
                >
                  <div class="chat-model-menu-dot">{{ (p.name || p.provider || '?').charAt(0).toUpperCase() }}</div>
                  <div class="chat-model-menu-info">
                    <div class="chat-model-menu-name">
                      {{ p.name || p.provider }}
                      <span v-if="p.id === currentSessionModelId" class="chat-model-menu-tag">本对话</span>
                    </div>
                    <div class="chat-model-menu-sub">{{ p.model || '(未填)' }}</div>
                  </div>
                  <span v-if="p.id === currentSessionModelId" class="chat-model-menu-check">✓</span>
                </div>
              </div>
            </div>
          </div>
          <button class="btn-ghost" @click="clearCurrent">清空当前</button>
        </div>
      </div>
      <div class="chat-messages" ref="messagesEl">
        <div v-for="(msg, i) in currentMessages" :key="i" class="chat-msg" :class="msg.role">
          <div class="chat-avatar" :class="msg.role">
            <span v-if="msg.role === 'user'">我</span>
            <svg v-else viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <rect x="4" y="7" width="16" height="12" rx="2.5"/>
              <line x1="12" y1="3" x2="12" y2="7"/>
              <circle cx="12" cy="2.5" r="1.2" fill="currentColor" stroke="none"/>
              <circle cx="9" cy="13" r="1.5" fill="currentColor" stroke="none"/>
              <circle cx="15" cy="13" r="1.5" fill="currentColor" stroke="none"/>
              <path d="M9.5 16.5h5"/>
            </svg>
          </div>
          <div class="chat-bubble-wrap">
            <div v-if="msg.images && msg.images.length" class="chat-msg-images">
              <img
                v-for="(img, idx) in msg.images"
                :key="idx"
                :src="img"
                class="chat-msg-image"
                @click="previewImage(img)"
              >
            </div>
            <!-- 报告卡片（点击耗时折叠/展开思考时间线，标题摘要章节始终显示） -->
            <div v-if="msg.report && msg.report.type === 'report'" class="chat-report-card">
              <div class="chat-report-header">
                <span class="chat-report-badge" :class="msg.report.status">{{ msg.report.status === 'completed' ? '已完成' : '进行中' }}</span>
                <span
                  class="chat-report-duration-toggle"
                  :class="{ expanded: msg.thinkingExpanded !== false }"
                  @click="msg.thinkingExpanded = !msg.thinkingExpanded"
                  title="点击折叠/展开思考时间线"
                >
                  总耗时 {{ totalDurationSeconds(msg) }}秒
                  <span class="chat-report-collapse-arrow" :class="{ expanded: msg.thinkingExpanded !== false }">▼</span>
                </span>
              </div>
              <!-- 思考过程时间线：由头部控制折叠（默认展开） -->
              <div v-if="msg.thinkingExpanded !== false && msg.timeline && msg.timeline.length" class="chat-thinking-inline">
                <div class="chat-thinking-inline-header">
                  <span class="chat-thinking-inline-icon">🧠</span>
                  <span v-if="msg.thinkingActive" class="chat-thinking-inline-title active">
                    思考中...
                    <span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
                  </span>
                  <span v-else class="chat-thinking-inline-title">思考过程</span>
                </div>
                <div class="chat-thinking-inline-body">
                  <div class="chat-timeline">
                    <div v-for="(item, idx) in msg.timeline" :key="idx" class="chat-timeline-item">
                      <!-- 思考项：内容直接可见 -->
                      <div v-if="item.type === 'thinking'" class="timeline-thinking">
                        <div class="timeline-thinking-header">
                          <span class="timeline-icon">💭</span>
                          <span class="timeline-label">思考中。。。</span>
                          <span class="timeline-elapsed" style="margin-left:auto">耗时 {{ formatThinkingDuration(item.elapsed) }}</span>
                        </div>
                        <div class="timeline-thinking-content" v-html="renderMarkdown(item.content)"></div>
                      </div>
                      <!-- 命令项：可展开/折叠，结果直接可见 -->
                      <div v-else-if="item.type === 'command'" class="timeline-command">
                        <div class="timeline-command-header" @click="toggleTimelineItem(msg, idx)">
                          <span class="timeline-icon" :class="item.status">{{ item.status === 'error' ? '❌' : '✅' }}</span>
                          <span class="timeline-label">已执行 {{ getCommandIndex(msg, idx) }} 条命令</span>
                          <span class="timeline-command-name">{{ toolDisplayName(item.name) }}</span>
                          <span class="timeline-elapsed">耗时 {{ formatThinkingDuration(item.elapsed) }}</span>
                          <span class="timeline-arrow" :class="{ expanded: isTimelineItemExpanded(msg, idx) }">▼</span>
                        </div>
                        <div v-if="isTimelineItemExpanded(msg, idx)" class="timeline-command-result"><pre>{{ item.result }}</pre></div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <!-- 报告标题/摘要/章节：始终显示 -->
              <div class="chat-report-title" v-html="renderMarkdownInline(msg.report.title)"></div>
              <div class="chat-report-summary" v-html="renderMarkdown(msg.report.summary)"></div>
              <!-- 其他章节（兼容旧报告/模型生成的章节） -->
              <div v-for="(sec, si) in msg.report.sections" :key="si" class="chat-report-section">
                <div class="chat-report-section-title">{{ sec.heading }}</div>
                <div class="chat-report-section-body" v-html="renderSectionItems(sec.items)"></div>
              </div>
            </div>
            <!-- 无报告但有时间线（任务运行初期），单独展示思考过程 -->
            <div v-else-if="msg.timeline && msg.timeline.length" class="chat-thinking-card">
              <div class="chat-thinking-header">
                <span class="chat-thinking-icon">🧠</span>
                <span v-if="msg.thinkingActive" class="chat-thinking-status active">
                  思考中...
                  <span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
                </span>
                <span v-else class="chat-thinking-status">思考过程</span>
              </div>
              <div class="chat-thinking-body">
                <div class="chat-timeline">
                  <div v-for="(item, idx) in msg.timeline" :key="idx" class="chat-timeline-item">
                    <!-- 思考项：内容直接可见 -->
                    <div v-if="item.type === 'thinking'" class="timeline-thinking">
                      <div class="timeline-thinking-header">
                        <span class="timeline-icon">💭</span>
                        <span class="timeline-label">思考中。。。</span>
                        <span class="timeline-elapsed" style="margin-left:auto">耗时 {{ formatThinkingDuration(item.elapsed) }}</span>
                      </div>
                      <div class="timeline-thinking-content" v-html="renderMarkdown(item.content)"></div>
                    </div>
                    <!-- 命令项：可展开/折叠，结果直接可见 -->
                    <div v-else-if="item.type === 'command'" class="timeline-command">
                      <div class="timeline-command-header" @click="toggleTimelineItem(msg, idx)">
                        <span class="timeline-icon" :class="item.status">{{ item.status === 'error' ? '❌' : '✅' }}</span>
                        <span class="timeline-label">已执行 {{ getCommandIndex(msg, idx) }} 条命令</span>
                        <span class="timeline-command-name">{{ toolDisplayName(item.name) }}</span>
                        <span class="timeline-elapsed">耗时 {{ formatThinkingDuration(item.elapsed) }}</span>
                        <span class="timeline-arrow" :class="{ expanded: isTimelineItemExpanded(msg, idx) }">▼</span>
                      </div>
                      <div v-if="isTimelineItemExpanded(msg, idx)" class="timeline-command-result"><pre>{{ item.result }}</pre></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="chat-bubble"><div v-html="renderMarkdown(msg.text)"></div></div>
            <div class="chat-time">{{ formatTime(msg.time) }}</div>
          </div>
        </div>
        <div v-if="!currentMessages.length" style="display: flex; flex: 1; align-items: center; justify-content: center; color: var(--text-muted); gap: 10px;">
          <span style="font-size: 42px; opacity: .4;">💬</span>
          <span>开始新对话</span>
        </div>
      </div>
      <div class="chat-input-area" @dragover.prevent @drop="handleDrop">
        <div v-if="pendingImages.length" class="chat-input-images">
          <div v-for="(img, i) in pendingImages" :key="i" class="chat-input-image-item">
            <img :src="img.dataUrl" :alt="img.name">
            <button class="chat-input-image-del" @click="removePendingImage(i)" title="移除">✕</button>
          </div>
        </div>
        <div v-if="knowledgeBases.length" class="chat-kb-row">
          <span class="chat-kb-label">📚 知识库</span>
          <label v-for="kb in knowledgeBases" :key="kb.id" class="chat-kb-chip">
            <input type="checkbox" :value="kb.id" v-model="selectedKnowledgeIds" />
            <span class="chat-kb-chip-name">{{ kb.name }}</span>
            <span class="chat-kb-chip-count">{{ kb.chunk_count }}</span>
          </label>
        </div>
        <div class="chat-input-row">
          <button class="chat-upload" @click="triggerImageUpload" title="上传图片">＋</button>
          <textarea
            ref="inputEl"
            v-model="inputText"
            rows="1"
            placeholder="Agent 模式：描述任务，Agent 会自动分析、调用工具、连续执行…"
            @keydown.enter.exact.prevent="onEnterPress"
            @paste="handlePaste"
            @input="autoResize"
          ></textarea>
          <button class="chat-send agent-active" @click="send">➤</button>
        </div>
        <input
          ref="imageInput"
          type="file"
          accept="image/*"
          multiple
          style="display:none"
          @change="onImageSelected"
        >
      </div>
    </div>

    <div v-if="false" class="chat-resizer chat-resizer-right" :class="{ active: filesResizing }" @mousedown="startFilesResize"></div>

    <div v-if="false" class="chat-files" :class="{ collapsed: filesCollapsed }" :style="filesCollapsed ? {} : { width: filesWidth + 'px', flexShrink: 0 }">
      <div class="chat-files-head">
        <div class="chat-files-title-row">
          <div class="chat-files-title">
            <span class="chat-files-icon" @click="filesCollapsed = !filesCollapsed" style="cursor:pointer">📁</span>
            <div class="ws-picker" :class="{ open: wsPickerOpen }">
                  <div class="ws-picker-trigger" @click.stop="onWsPickerToggle">
                    <svg class="ws-picker-trigger-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"
                        :fill="wsPickerOpen ? 'var(--accent)' : 'rgba(139,92,246,.8)'"/>
                    </svg>
                    <span class="ws-picker-name">{{ wsName || '选择工作空间' }}</span>
                    <svg class="ws-picker-arrow" width="10" height="10" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                    </svg>
                  </div>
                  <div class="ws-picker-dropdown" v-if="wsPickerOpen">
                    <div class="ws-picker-header">
                      <span class="ws-picker-header-icon">📁</span>
                      <div class="ws-picker-header-text">
                        <div class="ws-picker-header-title">工作空间</div>
                        <div class="ws-picker-header-sub">共 {{ workspaceList.length }} 个</div>
                      </div>
                    </div>
                    <div class="ws-picker-list">
                      <div
                        v-for="ws in workspaceList"
                        :key="ws.id"
                        class="ws-picker-item"
                        :class="{ selected: ws.id === currentWorkspaceId }"
                        @click.stop="pickWorkspace(ws)"
                      >
                        <div class="ws-picker-item-left">
                          <svg v-if="ws.id === currentWorkspaceId" class="ws-picker-item-check" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M5 12l4 4L19 7" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                          </svg>
                          <span class="ws-picker-item-icon">📂</span>
                          <span class="ws-picker-item-name">{{ ws.name }}</span>
                        </div>
                        <button class="ws-picker-item-del" @click.stop="removeWorkspace(ws.id)" title="删除工作空间">
                          <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6"
                              stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                          </svg>
                        </button>
                      </div>
                      <div v-if="!workspaceList.length" class="ws-picker-empty">
                        <span style="font-size:20px;">🗂️</span>
                        <div style="margin-top:6px;">暂无工作空间</div>
                        <div style="font-size:11px;opacity:.8;">点击下方按钮添加一个本地目录</div>
                      </div>
                    </div>
                    <div class="ws-picker-actions">
                      <button class="ws-picker-btn-create" @click.stop="createWorkspace">
                        <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" style="flex-shrink:0;">
                          <path d="M5 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"
                            stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                          <path d="M9 11h6M12 8v6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        <span>打开本地目录</span>
                      </button>
                    </div>
                  </div>
                </div>
            <input
              ref="workspaceDirInput"
              type="file"
              webkitdirectory
              directory
              style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0;overflow:hidden"
              @change="onWorkspaceDirSelected"
            />
            <span class="chat-files-arrow" @click="filesCollapsed = !filesCollapsed" style="cursor:pointer; display:none;">{{ filesCollapsed ? '▸' : '▾' }}</span>
          </div>
          <div class="chat-files-actions" v-if="!filesCollapsed">
            <button class="chat-files-refresh" @click="loadWorkspaceFiles" :title="`刷新（${wsName || '加载中…'}）`">↻</button>
          </div>
        </div>
      </div>
      <div v-if="!filesCollapsed" class="chat-files-body">
        <div v-if="filesLoading" class="chat-files-empty">加载中…</div>
        <div v-else-if="filesError" class="chat-files-empty chat-files-error">{{ filesError }}</div>
        <div v-else-if="!currentWorkspaceId" class="chat-files-empty">
          还没有工作空间。<br>
          请到顶部「📁」选择工作空间 →「打开本地目录」添加一个目录。
        </div>
        <div v-else-if="!fileTree.length" class="chat-files-empty">空目录</div>
        <div v-else class="chat-files-tree">
          <div
            v-for="row in fileTreeRows"
            :key="row.node.rel + ':' + row.depth"
            class="chat-files-row"
            :class="{ dir: row.node.is_dir, file: !row.node.is_dir, expanded: expandedDirs[row.node.rel] }"
            :style="{ paddingLeft: (8 + row.depth * 14) + 'px' }"
            :title="row.node.rel"
            @click="onFileRowClick(row.node)"
          >
            <span class="chat-files-toggle">{{ row.node.is_dir ? (expandedDirs[row.node.rel] ? '▾' : '▸') : '' }}</span>
            <span class="chat-files-glyph">{{ fileGlyph(row.node) }}</span>
            <span class="chat-files-label">{{ row.node.name }}</span>
            <span class="chat-files-size" v-if="!row.node.is_dir">{{ formatSize(row.node.size) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showSkillPicker" class="skill-picker-overlay" @click.self="showSkillPicker = false">
      <div class="skill-picker-modal">
        <div class="skill-picker-header">
          <div class="skill-picker-title">{{ editingSessionId ? '管理会话技能' : '选择会话技能' }}</div>
          <button class="skill-picker-close" @click="showSkillPicker = false">✕</button>
        </div>
        <div class="skill-picker-sub">选择要在本次对话中携带的技能，AI 将自动调用它们</div>
        <div class="skill-picker-body">
          <div v-if="!availableSkills.length" class="skill-picker-empty">
            暂无可用技能，请先在「集成管理 → 技能管理」中添加
          </div>
          <div v-for="sk in availableSkills" :key="sk.id" class="skill-picker-item" :class="{ selected: isSkillSelected(sk.id), disabled: !sk.enabled }" @click="toggleSkill(sk)">
            <div class="skill-picker-check">{{ isSkillSelected(sk.id) ? '✓' : '' }}</div>
            <div class="skill-picker-icon" :style="{ background: sk.color || 'rgba(139, 92, 246, 0.12)' }">{{ sk.icon || '🛠️' }}</div>
            <div class="skill-picker-info">
              <div class="skill-picker-name">{{ sk.name }}</div>
              <div class="skill-picker-desc">{{ sk.desc }}</div>
            </div>
            <span v-if="!sk.enabled" class="skill-picker-disabled">已停用</span>
          </div>
        </div>
        <div class="skill-picker-footer">
          <span class="skill-picker-count">已选 {{ tempSelectedSkills.length }} 个技能</span>
          <div style="display:flex;gap:8px;">
            <button class="btn-ghost" @click="showSkillPicker = false">取消</button>
            <button class="btn-primary" @click="confirmSkillSelection">确认</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch, onUnmounted } from 'vue'
import wsManager from '../utils/wsManager.js'
import { appConfirm, appAlert, appPrompt } from '../utils/appDialog.js'

const sessions = ref([])
const currentId = ref(null)
const inputText = ref('')
const inputEl = ref(null)
const searchTerm = ref('')
const messagesEl = ref(null)
const showSkillPicker = ref(false)
const availableSkills = ref([])
const tempSelectedSkills = ref([])
const editingSessionId = ref(null)
const workspaceDirInput = ref(null)
const imageInput = ref(null)
const pendingImages = ref([])
const knowledgeBases = ref([])
const selectedKnowledgeIds = ref([])
const MAX_IMAGES = 4

const currentSession = computed(() => sessions.value.find(s => s.id === currentId.value))
const currentMessages = computed(() => currentSession.value?.messages || [])

const filteredSessions = computed(() => {
  const term = searchTerm.value.trim().toLowerCase()
  if (!term) return sessions.value
  return sessions.value.filter(s => s.title.toLowerCase().includes(term))
})

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// 步骤默认展开：Agent 边思考边显示，仅用户手动收起的步骤保持折叠
function isStepExpanded(msg, sti) {
  if (!msg.stepExpanded) return true
  return msg.stepExpanded[sti] !== false
}

function toggleStep(msg, sti) {
  if (!msg.stepExpanded) msg.stepExpanded = {}
  msg.stepExpanded[sti] = !isStepExpanded(msg, sti)
}

// ===== 时间线（思考过程）辅助方法 =====

// 时间线项默认折叠：命令结果点击后展开
function isTimelineItemExpanded(msg, idx) {
  if (!msg.timelineExpanded) return false
  return msg.timelineExpanded[idx] === true
}

function toggleTimelineItem(msg, idx) {
  if (!msg.timelineExpanded) msg.timelineExpanded = {}
  msg.timelineExpanded[idx] = !isTimelineItemExpanded(msg, idx)
}

// 计算这是第几条命令（从 1 开始）
function getCommandIndex(msg, idx) {
  if (!msg.timeline) return idx + 1
  let n = 0
  for (let i = 0; i <= idx; i++) {
    if (msg.timeline[i] && msg.timeline[i].type === 'command') n++
  }
  return n
}

// 工具名 -> 友好中文显示名
const TOOL_DISPLAY_NAMES = {
  grep_code: '查找文件',
  list_directory: '查看目录',
  read_file: '读取文件',
  write_file: '写入文件',
  run_python_code: '运行代码',
  run_command: '执行命令',
  http_request: '请求接口',
  get_weather: '查询天气',
  call_skill: '调用技能',
}

function toolDisplayName(name) {
  if (!name) return ''
  // 技能类工具 call_skill_xxx 也显示为"调用技能"
  if (name.startsWith('call_skill_')) return '调用技能'
  return TOOL_DISPLAY_NAMES[name] || name
}

// 思考耗时格式化：12s / 1m5s / --
function formatThinkingDuration(sec) {
  if (!sec || sec <= 0) return '--'
  sec = Math.round(sec)
  if (sec < 60) return `${sec}s`
  return `${Math.floor(sec / 60)}m${sec % 60}s`
}

// 根据时间线索引项的 elapsed 计算任务总耗时（秒）
function totalDurationSeconds(msg) {
  let total = 0
  if (msg.timeline && msg.timeline.length) {
    for (const item of msg.timeline) {
      if (item && item.elapsed && item.elapsed > total) total = item.elapsed
    }
  }
  if (msg.thinkingDuration && msg.thinkingDuration > total) total = msg.thinkingDuration
  return total
}

function renderMarkdown(text) {
  if (!text) return ''
  let html = String(text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) => {
    return `<pre><code${lang ? ` class="lang-${lang}"` : ''}>${code}</code></pre>`
  })
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')

  const lines = html.split('\n')
  const out = []
  let inTable = false
  let tableRows = []
  let inList = false
  let listType = null
  let listItems = []
  let inBlockquote = false
  let blockquoteLines = []
  let paraBuf = []

  function flushPara() {
    if (paraBuf.length) {
      out.push('<p>' + paraBuf.join(' ').trim() + '</p>')
      paraBuf = []
    }
  }

  function flushList() {
    if (inList && listItems.length) {
      const tag = listType === 'ol' ? 'ol' : 'ul'
      out.push(`<${tag}>` + listItems.join('') + `</${tag}>`)
    }
    inList = false
    listType = null
    listItems = []
  }

  function flushBlockquote() {
    if (inBlockquote && blockquoteLines.length) {
      out.push('<blockquote>' + blockquoteLines.join('<br>') + '</blockquote>')
    }
    inBlockquote = false
    blockquoteLines = []
  }

  function flushTable() {
    if (inTable && tableRows.length) {
      let thead = ''
      let tbody = ''
      if (tableRows.length >= 2) {
        const headerCells = tableRows[0].map(c => `<th>${c.trim()}</th>`).join('')
        thead = `<thead><tr>${headerCells}</tr></thead>`
        const bodyRows = tableRows.slice(2).map(r => {
          const cells = r.map(c => `<td>${c.trim()}</td>`).join('')
          return `<tr>${cells}</tr>`
        }).join('')
        tbody = `<tbody>${bodyRows}</tbody>`
      } else {
        const rows = tableRows.map(r => {
          const cells = r.map(c => `<td>${c.trim()}</td>`).join('')
          return `<tr>${cells}</tr>`
        }).join('')
        tbody = `<tbody>${rows}</tbody>`
      }
      out.push(`<div class="md-table-wrap"><table>${thead}${tbody}</table></div>`)
    }
    inTable = false
    tableRows = []
  }

  const tableLineRegex = /^\s*\|(.+)\|\s*$/
  const tableSepRegex = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      flushPara()
      flushList()
      flushBlockquote()
      flushTable()
      continue
    }

    if (tableLineRegex.test(trimmed)) {
      flushPara()
      flushList()
      flushBlockquote()
      const cells = trimmed.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|')
      if (!inTable) {
        inTable = true
        tableRows = []
      }
      tableRows.push(cells)
      continue
    } else if (inTable && tableSepRegex.test(trimmed)) {
      tableRows.push(trimmed.split('|'))
      continue
    } else {
      flushTable()
    }

    if (trimmed.startsWith('> ')) {
      flushPara()
      flushList()
      inBlockquote = true
      blockquoteLines.push(trimmed.slice(2))
      continue
    } else {
      flushBlockquote()
    }

    const ulMatch = trimmed.match(/^[-*+]\s+(.+)$/)
    const olMatch = trimmed.match(/^\d+\.\s+(.+)$/)
    if (ulMatch) {
      flushPara()
      if (!inList || listType !== 'ul') { flushList(); inList = true; listType = 'ul' }
      listItems.push(`<li>${ulMatch[1]}</li>`)
      continue
    } else if (olMatch) {
      flushPara()
      if (!inList || listType !== 'ol') { flushList(); inList = true; listType = 'ol' }
      listItems.push(`<li>${olMatch[1]}</li>`)
      continue
    } else {
      flushList()
    }

    let heading = null
    if (trimmed.startsWith('### ')) heading = { level: 3, text: trimmed.slice(4) }
    else if (trimmed.startsWith('## ')) heading = { level: 2, text: trimmed.slice(3) }
    else if (trimmed.startsWith('# ')) heading = { level: 1, text: trimmed.slice(2) }
    if (heading) {
      flushPara()
      out.push(`<h${heading.level}>${heading.text}</h${heading.level}>`)
      continue
    }

    if (trimmed.startsWith('---') || trimmed.startsWith('***') || trimmed.startsWith('___')) {
      flushPara()
      out.push('<hr>')
      continue
    }

    paraBuf.push(line.trim())
  }

  flushPara()
  flushList()
  flushBlockquote()
  flushTable()

  html = out.join('\n')

  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>')
  html = html.replace(/~~([^~]+)~~/g, '<del>$1</del>')
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')

  return `<div class="md">${html}</div>`
}

function renderSectionItems(items) {
  if (!items || !items.length) return ''
  const parts = items.map(item => {
    if (typeof item === 'string') {
      if (item.includes('\n') || item.includes('```') || item.includes('|') || item.startsWith('#') || item.startsWith('-') || item.startsWith('1.')) {
        return `<div class="report-section-text md">${renderMarkdown(item)}</div>`
      }
      return `<li>${renderMarkdownInline(item)}</li>`
    }
    if (item && typeof item === 'object') {
      if (item.type === 'text' || item.content) {
        return `<div class="report-section-text md">${renderMarkdown(item.content || item.text || '')}</div>`
      }
      if (item.type === 'code') {
        return `<pre class="report-section-code"><code>${escapeHtml(item.content || item.code || '')}</code></pre>`
      }
      return `<li>${renderMarkdownInline(item.content || item.text || '')}</li>`
    }
    return `<li>${renderMarkdownInline(String(item))}</li>`
  })
  const hasList = items.some(item => {
    if (typeof item !== 'string') return !!(item && item.type && item.type !== 'text' && item.type !== 'code')
    return !(item.includes('\n') || item.includes('```') || item.includes('|') || item.startsWith('#') || item.startsWith('-') || item.startsWith('1.'))
  })
  if (hasList && !items.some(item => typeof item === 'object' && (item.type === 'text' || item.type === 'code'))) {
    const allStrings = items.every(item => typeof item === 'string')
    if (allStrings && !items.some(item => item.includes('\n') || item.includes('```') || item.includes('|') || item.startsWith('#') || item.startsWith('-') || item.startsWith('1.'))) {
      return `<ul class="chat-report-list">${parts.join('')}</ul>`
    }
  }
  return parts.join('')
}

function renderMarkdownInline(text) {
  if (!text) return ''
  return String(text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
}

function toggleReportStep(msg, stepId) {
  if (!msg.reportExpanded) msg.reportExpanded = {}
  msg.reportExpanded[stepId] = !msg.reportExpanded[stepId]
}

async function loadKnowledgeBases() {
  try {
    const res = await fetch('/api/knowledge')
    if (res.ok) {
      const data = await res.json()
      knowledgeBases.value = data.knowledge_bases || []
    }
  } catch {}
}

async function loadAvailableSkills() {
  // 优先加载技能管理（后端 skills.json）里的技能
  try {
    const res = await fetch('/api/skills')
    if (res.ok) {
      const data = await res.json()
      if (Array.isArray(data.skills) && data.skills.length) {
        availableSkills.value = data.skills.map(sk => ({
          id: sk.id, name: sk.name, icon: sk.icon || '🛠️',
          type: sk.type, url: sk.url || '', enabled: sk.enabled !== false,
        }))
        return
      }
    }
  } catch {}
  // 兜底：本地模板技能
  try {
    const saved = localStorage.getItem('skills')
    if (saved) availableSkills.value = JSON.parse(saved)
  } catch {}
}

function isSkillSelected(skillId) {
  return tempSelectedSkills.value.some(s => s.id === skillId)
}

function toggleSkill(skill) {
  if (!skill.enabled) return
  const idx = tempSelectedSkills.value.findIndex(s => s.id === skill.id)
  if (idx >= 0) {
    tempSelectedSkills.value.splice(idx, 1)
  } else {
    tempSelectedSkills.value.push({ id: skill.id, name: skill.name, icon: skill.icon, type: skill.type, url: skill.url })
  }
}

function openNewSessionDialog() {
  loadAvailableSkills()
  editingSessionId.value = null
  tempSelectedSkills.value = []
  showSkillPicker.value = true
}

function editSkills() {
  const s = currentSession.value
  if (!s) return
  loadAvailableSkills()
  editingSessionId.value = s.id
  tempSelectedSkills.value = [...(s.skills || [])]
  showSkillPicker.value = true
}

function confirmSkillSelection() {
  if (editingSessionId.value) {
    const s = sessions.value.find(x => x.id === editingSessionId.value)
    if (s) {
      s.skills = [...tempSelectedSkills.value]
      saveSessions()
    }
  } else {
    const id = Date.now().toString()
    sessions.value.unshift({
      id,
      title: '新对话',
      time: Date.now(),
      messages: [],
      skills: [...tempSelectedSkills.value],
      modelPresetId: globalDefaultPresetId.value || '',  // 新建会话时绑定当前默认模型
      memoryEnabled: true,  // 每个新会话自动开启跨会话记忆
    })
    currentId.value = id
    saveSessions()
  }
  showSkillPicker.value = false
}

// 切换会话记忆开关（会话级，点击会话列表的 🧠 图标）
function toggleSessionMemory(s) {
  s.memoryEnabled = !(s.memoryEnabled !== false)
  saveSessions()
}

async function deleteSession(id) {
  // 原生 confirm() 在 Electron 桌面端关闭后窗口系统级焦点无法恢复（输入框打不了字），
  // 改用应用内自定义对话框，全程页面内交互，不触发系统焦点切换。
  if (!(await appConfirm('确定删除该会话？'))) return
  sessions.value = sessions.value.filter(s => s.id !== id)
  if (currentId.value === id) currentId.value = sessions.value[0]?.id || null
  saveSessions()
  // 焦点还给输入框，删除后可继续直接打字
  nextTick(() => {
    const el = inputEl.value
    if (el) {
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
    }
  })
}

async function clearCurrent() {
  const s = currentSession.value
  if (!s) return
  if (!(await appConfirm('确定清空当前会话的消息记录吗？'))) return
  s.messages = [{ role: 'ai', text: '当前会话已清空，请重新输入。', time: Date.now() }]
  saveSessions()
}

// ===== 当前会话模型（会话级，每个对话可独立切换） =====
const presets = ref([])
const presetsById = computed(() => {
  const m = {}
  for (const p of presets.value) m[p.id] = p
  return m
})
const modelMenuOpen = ref(false)
const modelLoading = ref(false)

// 会话绑定模型：当前会话的 modelPresetId（未设置时回退到全局激活）
const currentSessionModelId = computed(() => {
  const s = currentSession.value
  return s?.modelPresetId || globalDefaultPresetId.value || ''
})

const currentSessionPreset = computed(() => {
  const id = currentSessionModelId.value
  if (!id) return null
  return presetsById.value[id] || null
})

const currentModelName = computed(() =>
  currentSessionPreset.value?.name || currentSessionPreset.value?.provider || '未配置',
)
const currentModelSub = computed(() =>
  currentSessionPreset.value?.model || '点击右上角切换',
)
const currentModelFull = computed(() => {
  const p = currentSessionPreset.value
  if (!p) return '尚未配置模型，请到顶栏或系统设置中选择'
  return `${p.name || p.provider} · ${p.model || '(未填)'}${p.base_url ? ' · ' + p.base_url : ''}`
})
const currentModelInitial = computed(() => {
  const n = currentSessionPreset.value?.name || currentSessionPreset.value?.provider || '?'
  return (n.charAt(0) || '?').toUpperCase()
})

// 全局默认（顶栏激活预设），仅用于「新建会话时」未指定时的默认
const globalDefaultPresetId = ref('')

async function loadPresetsList() {
  modelLoading.value = true
  try {
    const res = await fetch('/api/model-presets')
    if (!res.ok) return
    const data = await res.json()
    presets.value = data.presets || []
    globalDefaultPresetId.value = data.active_id || ''
  } catch (e) { /* 静默 */ }
  finally { modelLoading.value = false }
}

function loadActiveModel() { loadPresetsList() }

function toggleModelMenu() {
  modelMenuOpen.value = !modelMenuOpen.value
  if (modelMenuOpen.value) loadPresetsList()
}

function pickModelForSession(p) {
  const s = currentSession.value
  if (!s) return
  if (s.modelPresetId === p.id) {
    modelMenuOpen.value = false
    return
  }
  s.modelPresetId = p.id
  // 立刻反映在 UI 上
  saveSessions()
  modelMenuOpen.value = false
  showMessage(`本对话已切换到「${p.name || p.provider}」`)
}

function goPresetAdmin() {
  modelMenuOpen.value = false
  window.location.hash = '#/settings'
}

function showMessage(text) {
  // 简易提示，复用 toast 也可以，这里直接用一个临时变量
  saveMessage.value = { type: 'ok', text }
  setTimeout(() => { saveMessage.value = null }, 2000)
}
const saveMessage = ref(null)

// 全局 model-changed 事件：更新全局默认（新建会话时使用）
function onModelChanged() {
  loadPresetsList()
}

// 点击其它位置关闭 dropdown
function onDocClickChat(e) {
  if (!modelMenuOpen.value) return
  const el = e.target
  if (el && el.closest && el.closest('.chat-current-model-wrap')) return
  modelMenuOpen.value = false
}

function triggerImageUpload() {
  if (imageInput.value) imageInput.value.click()
}

function onImageSelected(event) {
  const files = Array.from(event.target.files || [])
  if (!files.length) return
  for (const file of files) {
    if (pendingImages.value.length >= MAX_IMAGES) {
      showMessage(`最多上传 ${MAX_IMAGES} 张图片`)
      break
    }
    if (!file.type || !file.type.startsWith('image/')) continue
    compressImage(file)
      .then(dataUrl => { pendingImages.value.push({ name: file.name, dataUrl }) })
      .catch(() => showMessage('图片读取失败：' + file.name))
  }
  if (imageInput.value) imageInput.value.value = ''
}

// 压缩图片到最长边 1024px 的 JPEG，避免 base64 撑爆 localStorage（聊天记录存储于此）
function compressImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      try {
        const MAX = 1024
        const scale = Math.min(1, MAX / Math.max(img.width, img.height))
        const width = Math.max(1, Math.round(img.width * scale))
        const height = Math.max(1, Math.round(img.height * scale))
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const ctx = canvas.getContext('2d')
        ctx.drawImage(img, 0, 0, width, height)
        resolve(canvas.toDataURL('image/jpeg', 0.85))
      } catch (e) {
        reject(e)
      } finally {
        URL.revokeObjectURL(url)
      }
    }
    img.onerror = (e) => { URL.revokeObjectURL(url); reject(e) }
    img.src = url
  })
}

// 处理粘贴图片（textarea 内）
function handlePaste(event) {
  const items = (event.clipboardData || event.originalEvent.clipboardData).items
  if (!items) return
  let handled = false
  for (const item of items) {
    if (item.type.indexOf('image') !== -1) {
      const file = item.getAsFile()
      if (!file) continue
      event.preventDefault()
      handled = true
      if (pendingImages.value.length >= MAX_IMAGES) {
        showMessage(`最多上传 ${MAX_IMAGES} 张图片`)
        break
      }
      compressImage(file)
        .then(dataUrl => { pendingImages.value.push({ name: `粘贴图片${Date.now()}.jpg`, dataUrl }) })
        .catch(() => showMessage('图片读取失败'))
    }
  }
  if (handled) showMessage('图片已粘贴到输入框，点击发送即可')
}

function autoResize() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  const lineHeight = 22
  const minHeight = lineHeight * 2 + 24
  const maxHeight = lineHeight * 10 + 24
  const scrollHeight = el.scrollHeight
  let h = Math.max(minHeight, scrollHeight)
  if (h > maxHeight) h = maxHeight
  el.style.height = h + 'px'
  el.style.overflowY = scrollHeight > maxHeight ? 'auto' : 'hidden'
}

// 回车发送（输入法组合期间不触发，避免中文选字按回车被误发送）
function onEnterPress(e) {
  if (e.isComposing || e.keyCode === 229) return
  send()
}

// 全局粘贴监听：点击对话框其他位置时 Ctrl+V 也能粘贴图片
function handleGlobalPaste(event) {
  const target = event.target
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
    return
  }
  const items = (event.clipboardData || event.originalEvent?.clipboardData)?.items
  if (!items) return
  let hasImage = false
  for (const item of items) {
    if (item.type.indexOf('image') !== -1) { hasImage = true; break }
  }
  if (!hasImage) return
  event.preventDefault()
  for (const item of items) {
    if (item.type.indexOf('image') !== -1) {
      const file = item.getAsFile()
      if (!file) continue
      if (pendingImages.value.length >= MAX_IMAGES) {
        showMessage(`最多上传 ${MAX_IMAGES} 张图片`)
        break
      }
      compressImage(file)
        .then(dataUrl => { pendingImages.value.push({ name: `粘贴图片${Date.now()}.jpg`, dataUrl }) })
        .catch(() => showMessage('图片读取失败'))
    }
  }
  showMessage('图片已粘贴到输入框，点击发送即可')
}

function removePendingImage(i) {
  pendingImages.value.splice(i, 1)
}

// 拖放图片到输入区域
function handleDrop(event) {
  const files = Array.from(event.dataTransfer?.files || [])
  if (!files.length) return
  for (const file of files) {
    if (pendingImages.value.length >= MAX_IMAGES) {
      showMessage(`最多上传 ${MAX_IMAGES} 张图片`)
      break
    }
    if (!file.type || !file.type.startsWith('image/')) continue
    compressImage(file)
      .then(dataUrl => { pendingImages.value.push({ name: file.name, dataUrl }) })
      .catch(() => showMessage('图片读取失败：' + file.name))
  }
}

function previewImage(dataUrl) {
  window.open(dataUrl, '_blank')
}

async function send() {
  const text = inputText.value.trim()
  const hasImages = pendingImages.value.length > 0
  if (!text && !hasImages) return
  let s = currentSession.value
  // 没有会话时自动创建一个（不弹窗拦截，避免"输入不了/发不出去"的感觉）
  if (!s) {
    const id = Date.now().toString()
    s = {
      id,
      title: '新对话',
      time: Date.now(),
      messages: [],
      skills: [],
      modelPresetId: globalDefaultPresetId.value || '',
      memoryEnabled: true,  // 自动开启会话记忆
      sending: false,
    }
    sessions.value.unshift(s)
    currentId.value = id
    saveSessions()
  }
  if (s.sending) return

  // 会话中心快捷指令：提交代码（任何模式下都优先拦截）
  if (text.startsWith('提交代码') && !hasImages) {
    const customMsg = text.slice(4).trim()
    const commitMessage = customMsg || 'chore: 通过会话中心提交代码'
    return sendGitCommit(s, text, commitMessage)
  }

  // 所有消息一律走 Agent 模式（含图片）
  return sendAgent(s, text, pendingImages.value)
}

// ===== 快捷指令：提交代码到 GitHub =====
async function sendGitCommit(s, userText, commitMessage) {
  // 1) 推入用户消息
  s.messages.push({ role: 'user', text: userText, time: Date.now() })
  s.title = userText.slice(0, 20)
  inputText.value = ''
  pendingImages.value = []
  await scrollToBottom(true)

  // 2) 预占 AI 消息
  s.messages.push({ role: 'ai', text: '⏳ 正在提交代码…', time: Date.now(), pending: true })
  await scrollToBottom(true)

  s.sending = true
  saveSessions()

  function updateAiMsg(patch) {
    const last = s.messages[s.messages.length - 1]
    if (last && last.role === 'ai') {
      Object.assign(last, patch)
    }
  }

  try {
    // 先查询工作区状态，无变更则不调用提交
    const wsParam = currentWorkspaceId.value ? `?workspace_id=${encodeURIComponent(currentWorkspaceId.value)}` : ''
    const statusRes = await fetch(`/api/git/status${wsParam}`)
    const statusData = await statusRes.json()
    if (!statusRes.ok) {
      updateAiMsg({ text: `❌ 状态检查失败：${statusData.error || `HTTP ${statusRes.status}`}`, error: true, pending: false })
    } else if (statusData.clean) {
      updateAiMsg({ text: 'ℹ️ 当前没有可提交的变更，无需提交代码。', pending: false })
    } else {
      const res = await fetch('/api/git/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo: 'https://github.com/zxzxf/taofei_app.git',
          branch: 'main',
          message: commitMessage,
          workspace_id: currentWorkspaceId.value || undefined,
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        updateAiMsg({ text: `❌ 提交失败：${data.error || `HTTP ${res.status}`}`, error: true, pending: false })
      } else {
        updateAiMsg({
          text: `✅ 代码已提交并推送至 GitHub\n\n- 分支：${data.branch || 'main'}\n- 提交：${(data.commit || '').split(' ')[1] || data.commit || '-'}\n- 消息：${commitMessage}`,
          pending: false,
        })
        s.time = Date.now()
      }
    }
  } catch (e) {
    updateAiMsg({ text: `❌ 提交异常：${e.message || e}\n\n请确认后端服务已启动。`, error: true, pending: false })
  } finally {
    s.sending = false
    saveSessions()
    await scrollToBottom()
  }
}

// ===== Agent 模式：ReAct 循环 =====

// SSE/WS 异常时的兜底轮询
function fallbackPoll(task_id, aiMsg, s) {
  const pollInterval = setInterval(async () => {
    try {
      const sr = await fetch(`/api/status/${task_id}`)
      if (!sr.ok) return
      const task = await sr.json()
      aiMsg.agentSteps = (task.steps || []).map(st => ({
        name: st.name,
        status: st.status,
        time: st.time || '',
        output: st.output || '',
      }))
      // 捕获时间线（思考+命令+结果）
      if (task.timeline && task.timeline.length) {
        aiMsg.timeline = task.timeline
        aiMsg.thinkingDuration = task.thinking_duration || 0
        aiMsg.thinkingActive = task.status === 'running'
      } else if (task.thinking) {
        aiMsg.thinking = task.thinking
        aiMsg.thinkingDuration = task.thinking_duration || 0
        aiMsg.thinkingActive = task.status === 'running'
      }
      const result = task.result
      if (result && typeof result === 'object' && result.type === 'report') {
        aiMsg.report = result
        aiMsg.text = ''
      }
      if (task.status === 'running') {
        const stepText = `⏳ ${task.current_step || 'Agent 正在执行…'}`
        if (aiMsg.report) {
          aiMsg.report.summary = stepText
        } else {
          aiMsg.text = stepText
        }
      } else if (task.status === 'completed') {
        const finalResult = task.result
        if (finalResult && typeof finalResult === 'object' && finalResult.type === 'report') {
          aiMsg.report = finalResult
          aiMsg.text = ''
        } else if (!aiMsg.report) {
          aiMsg.text = finalResult || '(Agent 无返回结果)'
        }
        aiMsg.pending = false
        clearInterval(pollInterval)
        s.sending = false
        s.time = Date.now()
        saveSessions()
      } else if (task.status === 'failed') {
        aiMsg.text = `❌ Agent 执行失败：${task.error || '未知错误'}`
        aiMsg.pending = false
        aiMsg.error = true
        clearInterval(pollInterval)
        s.sending = false
        saveSessions()
      }
      scrollToBottom()
    } catch { /* 忽略轮询错误 */ }
  }, 1500)
}

async function sendAgent(s, text, images = []) {
  // 0) 收集当前会话历史（不包含当前请求和 pending 消息）
  const history = s.messages
    .filter(m => !m.pending)
    .map(m => ({
      role: m.role,
      text: m.text || '',
      images: m.images || [],
    }))

  // 1) 推入用户消息（含图片）
  s.messages.push({ role: 'user', text, time: Date.now(), images: images.map(i => i.dataUrl) })
  s.title = (text || '图片消息').slice(0, 20)
  inputText.value = ''
  pendingImages.value = []
  await scrollToBottom(true)

  // 2) 预占一条 AI 消息
  s.messages.push({ role: 'ai', text: '⏳ Agent 正在思考…', time: Date.now(), pending: true, agentSteps: [], showReportSteps: true, stepExpanded: {}, thinking: '', thinkingDuration: 0, thinkingActive: true, thinkingExpanded: true, timeline: [], timelineExpanded: {} })
  const aiMsg = s.messages[s.messages.length - 1]
  await scrollToBottom(true)

  s.sending = true
  saveSessions()

  function applyTaskUpdate(task) {
    aiMsg.agentSteps = (task.steps || []).map(st => ({
      name: st.name,
      status: st.status,
      time: st.time || '',
      output: st.output || '',
    }))
    // 捕获时间线（思考+命令+结果）
    if (task.timeline && task.timeline.length) {
      aiMsg.timeline = task.timeline
      aiMsg.thinkingActive = task.status === 'running'
      aiMsg.thinkingDuration = task.thinking_duration || 0
    } else if (task.thinking) {
      aiMsg.thinking = task.thinking
      aiMsg.thinkingDuration = task.thinking_duration || 0
      aiMsg.thinkingActive = task.status === 'running'
    }
    const result = task.result
    if (result && typeof result === 'object' && result.type === 'report') {
      aiMsg.report = result
      aiMsg.text = ''
    }
    if (task.status === 'running') {
      const stepText = `⏳ ${task.current_step || 'Agent 正在执行…'}`
      if (aiMsg.report) {
        aiMsg.report.summary = stepText
      } else {
        aiMsg.text = stepText
      }
    }
    saveSessions()
    scrollToBottom()
  }

  function finalizeTask(task) {
    // 捕获最终时间线/思考内容
    if (task.timeline && task.timeline.length) {
      aiMsg.timeline = task.timeline
      aiMsg.thinkingDuration = task.thinking_duration || 0
      aiMsg.thinkingActive = false
    } else if (task.thinking) {
      aiMsg.thinking = task.thinking
      aiMsg.thinkingDuration = task.thinking_duration || 0
      aiMsg.thinkingActive = false
    }
    if (task.status === 'completed') {
      const result = task.result
      if (result && typeof result === 'object' && result.type === 'report') {
        aiMsg.report = result
        aiMsg.text = ''
      } else if (!aiMsg.report) {
        aiMsg.text = result || '(Agent 无返回结果)'
      }
      aiMsg.pending = false
    } else if (task.status === 'cancelled') {
      aiMsg.text = '⏹️ 已取消'
      aiMsg.pending = false
    } else if (task.status === 'failed') {
      aiMsg.text = `❌ Agent 执行失败：${task.error || '未知错误'}`
      aiMsg.pending = false
      aiMsg.error = true
    }
    s.sending = false
    s.time = Date.now()
    saveSessions()
    scrollToBottom()
  }

  function useFallback(taskId) {
    fallbackPoll(taskId, aiMsg, s)
  }

  try {
    // 3) 启动 Agent 任务
    const startRes = await fetch('/api/agent/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request: text,
        model_preset_id: s.modelPresetId || globalDefaultPresetId.value || null,
        workspace_id: currentWorkspaceId.value || null,
        images: images.map(i => i.dataUrl),
        skill_ids: (s.skills || []).map(sk => sk.id),
        knowledge_ids: selectedKnowledgeIds.value,
        memory_enabled: (s.memoryEnabled !== false) && !!currentWorkspaceId.value,
        history,
      }),
    })
    if (!startRes.ok) {
      let errMsg = `HTTP ${startRes.status}`
      try { const d = await startRes.json(); errMsg = d.error || errMsg } catch {}
      aiMsg.text = `❌ Agent 启动失败：${errMsg}`
      aiMsg.pending = false
      aiMsg.error = true
      s.sending = false
      saveSessions()
      return
    }
    const { task_id } = await startRes.json()

    // 4) 优先走 WebSocket 订阅；连接未就绪时降级 SSE
    if (wsManager.status === 'connected') {
      const unsub = wsManager.subscribe(task_id, (msg) => {
        if (msg.type === 'task_update') {
          applyTaskUpdate(msg.task)
        } else if (msg.type === 'task_done') {
          applyTaskUpdate(msg.task)
          finalizeTask(msg.task)
          unsub()
        }
      })
      // 保存 unsub 用于清理
      aiMsg._wsUnsub = unsub
      aiMsg._taskId = task_id
    } else {
      // WS 未连接，降级为 SSE
      const es = new EventSource(`/api/agent/stream/${task_id}`)
      aiMsg._es = es
      aiMsg._taskId = task_id

      es.onmessage = (e) => {
        try {
          const task = JSON.parse(e.data)
          applyTaskUpdate(task)
        } catch { /* 忽略解析错误 */ }
      }
      es.addEventListener('done', (e) => {
        try {
          const task = JSON.parse(e.data)
          applyTaskUpdate(task)
          finalizeTask(task)
        } catch { /* 忽略解析错误 */ }
        es.close()
      })
      es.addEventListener('error', () => {
        es.close()
        if (aiMsg.pending) useFallback(task_id)
      })
      es.onerror = () => {
        es.close()
        if (aiMsg.pending) useFallback(task_id)
      }
    }
  } catch (e) {
    aiMsg.text = `❌ 网络错误：${e.message || e}`
    aiMsg.pending = false
    aiMsg.error = true
    s.sending = false
    saveSessions()
    await scrollToBottom()
  }
}

async function scrollToBottom(force = false) {
  await nextTick()
  const el = messagesEl.value
  if (!el) return
  // 流式更新时仅在用户贴近底部才自动跟随，避免回看历史时被强行拉回
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  if (force || nearBottom) el.scrollTop = el.scrollHeight
}

function saveSessions() {
  try {
    // 精简持久化：带报告卡片的消息不重复保存 agentSteps（报告 steps 已含全部过程与输出）
    const slim = sessions.value.map(s => ({
      ...s,
      messages: s.messages.map(m => {
        if (m.role === 'ai' && m.report && m.agentSteps) {
          const { agentSteps, ...rest } = m
          return rest
        }
        return m
      }),
    }))
    localStorage.setItem('chatSessions', JSON.stringify(slim))
  } catch (e) { console.error('保存会话失败', e) }
}

function presetNameById(id) {
  const p = presetsById.value[id]
  if (!p) return ''
  return p.name || p.provider || ''
}

function loadSessions() {
  try {
    const saved = localStorage.getItem('chatSessions')
    if (saved) {
      sessions.value = JSON.parse(saved)
      // 页面刚加载时不可能有任务在发送；重置残留的 sending/pending 状态，
      // 否则上次关闭前卡住的会话会一直"发送中"，输入框按回车没反应
      for (const s of sessions.value) {
        if (s.sending) s.sending = false
        for (const m of (s.messages || [])) {
          if (m.pending) {
            m.pending = false
            if (!m.text) m.text = '（上次任务被中断）'
          }
        }
      }
      currentId.value = sessions.value[0]?.id || null
    }
  } catch (e) { console.error('加载会话失败', e) }
}

function onWorkspaceChanged(evt) {
  // App.vue 切换工作空间时派发此事件
  const newId = evt?.detail?.current_id
  const newWorkspaces = evt?.detail?.workspaces
  if (newWorkspaces) {
    workspaceList.value = newWorkspaces
  }
  if (newId && newId !== currentWorkspaceId.value) {
    currentWorkspaceId.value = newId
    // 切换工作空间时重置展开状态
    expandedDirs.value = {}
  }
  // 无论 ID 是否变化都刷新一次文件列表，保证右侧内容与顶栏选择一致
  loadWorkspaceFiles()
}

onMounted(async () => {
  loadSessions()
  loadAvailableSkills()
  loadKnowledgeBases()
  await loadPresetsList()
  for (const s of sessions.value) {
    if (!s.modelPresetId && globalDefaultPresetId.value) {
      s.modelPresetId = globalDefaultPresetId.value
    }
  }
  saveSessions()
  window.addEventListener('taofei-model-changed', onModelChanged)
  window.addEventListener('taofei-workspace-changed', onWorkspaceChanged)
  document.addEventListener('click', onDocClickChat)
  document.addEventListener('click', onDocClickWorkspace)
  document.addEventListener('paste', handleGlobalPaste)
  await loadWorkspaceList()
  loadWorkspaceFiles()
  if (!sessions.value.length) {
    openNewSessionDialog()
  }
  // 建立 WebSocket 连接（全局单例，跨页面保持）
  wsManager.connect()
})

onUnmounted(() => {
  window.removeEventListener('taofei-model-changed', onModelChanged)
  window.removeEventListener('taofei-workspace-changed', onWorkspaceChanged)
  document.removeEventListener('click', onDocClickChat)
  document.removeEventListener('click', onDocClickWorkspace)
  document.removeEventListener('paste', handleGlobalPaste)
  // 清理所有仍在运行的任务订阅/SSE 连接
  for (const s of sessions.value) {
    for (const m of s.messages || []) {
      if (m._wsUnsub) { try { m._wsUnsub() } catch {} }
      if (m._es) { try { m._es.close() } catch {} }
    }
  }
})

watch(currentId, () => scrollToBottom(true))

// ===== 工作空间文件树（右侧面板） =====
const currentWorkspaceId = ref('')
const wsName = ref('')
const wsPath = ref('')
const fileTree = ref([])
const expandedDirs = ref({})
const filesLoading = ref(false)
const filesError = ref('')
const filesCollapsed = ref(false)

// ===== 工作空间选择器（头部） =====
const wsOpen = ref(false)
const wsSearch = ref('')

const currentWorkspaceName = computed(() => {
  const ws = workspaceList.value.find(w => w.id === currentWorkspaceId.value)
  return ws ? ws.name : '选择工作空间'
})

const filteredWorkspaces = computed(() => {
  const term = wsSearch.value.trim().toLowerCase()
  if (!term) return workspaceList.value
  return workspaceList.value.filter(w =>
    w.name.toLowerCase().includes(term) || (w.path || '').toLowerCase().includes(term)
  )
})

// 点击外部关闭工作空间下拉
const vClickOutside = {
  mounted(el, binding) {
    el._clickOutside = (e) => {
      if (!el.contains(e.target)) binding.value()
    }
    document.addEventListener('click', el._clickOutside)
  },
  unmounted(el) {
    document.removeEventListener('click', el._clickOutside)
  },
}

async function onWorkspaceChange(id) {
  wsOpen.value = false
  wsSearch.value = ''
  if (id) {
    try {
      const res = await fetch(`/api/workspaces/${id}/switch`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        currentWorkspaceId.value = data.current_id || id
      } else {
        currentWorkspaceId.value = id
      }
    } catch (e) {
      currentWorkspaceId.value = id
    }
  } else {
    currentWorkspaceId.value = ''
  }
  // 通知 App.vue 工作空间已切换
  window.dispatchEvent(new CustomEvent('taofei-workspace-changed', {
    detail: { current_id: currentWorkspaceId.value, workspaces: workspaceList.value },
  }))
  // 刷新文件树
  if (currentWorkspaceId.value) {
    expandedDirs.value = {}
    fileTree.value = []
    await loadWorkspaceFiles()
  } else {
    fileTree.value = []
    wsName.value = ''
    wsPath.value = ''
  }
}

function openLocalFolder() {
  wsOpen.value = false
  wsSearch.value = ''
  window.dispatchEvent(new CustomEvent('taofei-open-local-folder'))
}

function onDeleteWorkspace(id) {
  window.dispatchEvent(new CustomEvent('taofei-delete-workspace', { detail: { id } }))
}

// 左侧会话列表宽度拖拽
const sessionsWidth = ref(parseInt(localStorage.getItem('chatSessionsWidth') || '260'))
const resizing = ref(false)
const sidebarCollapsed = ref(localStorage.getItem('chatSidebarCollapsed') === 'true')

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('chatSidebarCollapsed', String(sidebarCollapsed.value))
}
let resizeStartX = 0
let resizeStartWidth = 0

function startResize(e) {
  resizing.value = true
  resizeStartX = e.clientX
  resizeStartWidth = sessionsWidth.value
  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', stopResize)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onResize(e) {
  if (!resizing.value) return
  const delta = e.clientX - resizeStartX
  const w = Math.min(500, Math.max(180, resizeStartWidth + delta))
  sessionsWidth.value = w
}

function stopResize() {
  resizing.value = false
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  localStorage.setItem('chatSessionsWidth', sessionsWidth.value)
}

// 右侧工作空间文件面板宽度拖拽
const filesWidth = ref(parseInt(localStorage.getItem('chatFilesWidth') || '300'))
const filesResizing = ref(false)
let filesResizeStartX = 0
let filesResizeStartWidth = 0

function startFilesResize(e) {
  if (filesCollapsed.value) return
  filesResizing.value = true
  filesResizeStartX = e.clientX
  filesResizeStartWidth = filesWidth.value
  document.addEventListener('mousemove', onFilesResize)
  document.addEventListener('mouseup', stopFilesResize)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onFilesResize(e) {
  if (!filesResizing.value) return
  const delta = filesResizeStartX - e.clientX // 向右拖拽减小，向左增大
  const w = Math.min(500, Math.max(200, filesResizeStartWidth + delta))
  filesWidth.value = w
}

function stopFilesResize() {
  filesResizing.value = false
  document.removeEventListener('mousemove', onFilesResize)
  document.removeEventListener('mouseup', stopFilesResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  localStorage.setItem('chatFilesWidth', filesWidth.value)
}

// 工作空间选择器
const wsPickerOpen = ref(false)
const workspaceList = ref([])

async function loadWorkspaceList() {
  try {
    const res = await fetch('/api/workspaces')
    if (res.ok) {
      const data = await res.json()
      workspaceList.value = data.workspaces || []
      if (!currentWorkspaceId.value && data.current_id) {
        currentWorkspaceId.value = data.current_id
      }
    }
  } catch (e) { /* ignore */ }
}

async function pickWorkspace(ws) {
  if (!ws || !ws.id) return
  if (ws.id === currentWorkspaceId.value) {
    wsPickerOpen.value = false
    return
  }
  currentWorkspaceId.value = ws.id
  wsName.value = ws.name
  wsPath.value = ws.path
  expandedDirs.value = {}
  wsPickerOpen.value = false
  // 持久化到后端：否则刷新页面后回退，且聊天上下文注入会用错工作空间
  try {
    await fetch(`/api/workspaces/${ws.id}/switch`, { method: 'POST' })
  } catch (_e) { /* 失败时仍保持本地切换 */ }
  loadWorkspaceFiles()
}

async function removeWorkspace(id) {
  if (!(await appConfirm('确定删除该工作空间？'))) return
  try {
    const res = await fetch(`/api/workspaces/${id}`, { method: 'DELETE' })
    if (res.ok) {
      const data = await res.json()
      workspaceList.value = workspaceList.value.filter(w => w.id !== id)
      if (currentWorkspaceId.value === id) {
        currentWorkspaceId.value = data.current_id || workspaceList.value[0]?.id || ''
        if (!currentWorkspaceId.value) {
          wsName.value = ''
          wsPath.value = ''
          fileTree.value = []
        }
      }
      loadWorkspaceFiles()
    }
  } catch (e) { /* ignore */ }
}

async function createWorkspace() {
  // 「打开本地目录」= 选择一个本地文件夹作为工作空间。
  // 优先级：
  //   1) 后端原生对话框 /api/browse-directory：Windows 现代资源管理器风格目录选择
  //      （接口会阻塞等待用户选择，前端设 120s 超时）
  //   2) Electron 桌面端：window.desktop.openDirectoryPicker()
  //   3) 浏览器 webkitdirectory input：上传目录副本（后端不支持原生对话框的环境）
  //   4) prompt 粘贴路径兜底。
  // 用户在任何一级真正点了取消 → 静默 return。

  // 原生对话框弹出期间收起页面下拉浮层，避免两层选择界面叠在一起
  wsPickerOpen.value = false

  const desktopApi = window.desktop
  const isElectron = typeof desktopApi === 'object' && desktopApi && typeof desktopApi.openDirectoryPicker === 'function'

  let path = ''

  // --- 路径 1：后端原生对话框 ---
  if (!path) {
    try {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 120000)
      const res = await fetch('/api/browse-directory', { signal: ctrl.signal })
      clearTimeout(timer)
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        if (data && data.canceled) return
        if (data && data.path) path = String(data.path)
      }
    } catch (_e) { /* 超时/网络异常 → 走下一级 */ }
  }

  // --- 路径 2：Electron 桌面端 ---
  if (!path && isElectron) {
    try {
      const pick = await desktopApi.openDirectoryPicker()
      if (pick && pick.canceled) return
      if (pick && pick.path) path = String(pick.path)
    } catch (_e) {}
  }

  // --- 路径 3：浏览器 webkitdirectory input ---
  if (!path && !isElectron && workspaceDirInput.value) {
    workspaceDirInput.value.click()
    return
  }

  // --- 路径 4：prompt 粘贴路径 ---
  if (!path) {
    const input = await appPrompt(
      '请粘贴或输入要打开的本地文件夹路径：\n（例如 D:\\projects\\my-app）',
      'D:\\workspaces\\taofei_plateform\\taofei_app',
      '打开本地目录',
    )
    if (!input) return
    path = input
  }

  await openWorkspaceByPath(path)
}

async function openWorkspaceByPath(path) {
  const trimmed = String(path).trim()
  if (!trimmed) return
  const name = trimmed.split(/[\\/]/).filter(Boolean).pop() || '新工作空间'

  try {
    const res = await fetch('/api/workspaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, path: trimmed }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      await appAlert('打开失败：' + (err.error || '路径无效'))
      return
    }
    const data = await res.json()
    if (data.workspace) {
      // 去重：检查是否已在列表中
      const exists = workspaceList.value.find(w => w.path === data.workspace.path)
      if (!exists) {
        workspaceList.value.push(data.workspace)
      }
      pickWorkspace(data.workspace)
    }
  } catch (e) {
    await appAlert('打开失败：' + (e.message || String(e)))
  }
}

async function onWorkspaceDirSelected(event) {
  const files = event?.target?.files
  if (!files || files.length === 0) return

  const firstPath = files[0].webkitRelativePath || files[0].name || ''
  const dirName = firstPath.split('/')[0] || 'workspace'

  const items = []
  for (const file of files) {
    try {
      const content = await file.text()
      const rel = file.webkitRelativePath || file.name
      if (!rel) continue
      items.push({ path: rel, content })
    } catch (_e) {
      // 二进制文件跳过文本读取
    }
  }

  if (items.length === 0) {
    await appAlert('未读取到可上传的文件，请重新选择目录。')
    return
  }

  try {
    const res = await fetch('/api/workspaces/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: items, directory_name: dirName }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      await appAlert('上传目录失败：' + (err.error || '请重试'))
      return
    }
    const data = await res.json()
    if (data.path) {
      await openWorkspaceByPath(data.path)
    } else {
      await appAlert('上传目录失败：后端未返回路径')
    }
  } catch (e) {
    await appAlert('上传目录失败：' + (e.message || String(e)))
  } finally {
    // 允许重复选择同一目录
    if (workspaceDirInput.value) workspaceDirInput.value.value = ''
  }
}

// 切换工作空间选择器下拉
function onWsPickerToggle() {
  wsPickerOpen.value = !wsPickerOpen.value
}

// 点击外部关闭工作空间选择器
function onDocClickWorkspace(e) {
  if (!wsPickerOpen.value) return
  const picker = document.querySelector('.ws-picker')
  if (picker && !picker.contains(e.target)) {
    wsPickerOpen.value = false
  }
}

// 把后端返回的扁平列表构造为嵌套树（按 '/' 拆 rel）
function buildTreeFromFlat(items) {
  if (!Array.isArray(items)) return []
  const rootChildren = new Map()
  for (const it of items) {
    if (!it) continue
    const parts = (it.rel || it.name || '').split('/').filter(Boolean)
    if (!parts.length) continue
    let cursor = rootChildren
    // 遍历中间层，创建/复用目录节点
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i]
      const key = parts.slice(0, i + 1).join('/')
      const existing = cursor.get(part)
      if (!existing) {
        cursor.set(part, { name: part, rel: key, is_dir: true, size: 0, children: new Map() })
      } else if (!existing.children || !(existing.children instanceof Map)) {
        // 路径上存在同名 leaf（非目录），把它升级为目录
        existing.is_dir = true
        existing.children = new Map()
      }
      cursor = cursor.get(part).children
    }
    const leafName = parts[parts.length - 1] || it.name
    const leafKey = it.rel || it.name || leafName
    if (!cursor) continue
    const prev = cursor.get(leafName)
    if (prev && prev.children instanceof Map) {
      // 已存在同名目录节点 → 保留目录的 children，其他字段用新 leaf 覆盖
      cursor.set(leafName, { ...prev, ...it, name: leafName, rel: leafKey, children: prev.children })
    } else {
      cursor.set(leafName, { name: leafName, ...it, rel: leafKey, children: null })
    }
  }
  // Map → Array，目录优先、再按字母排序
  function sortMap(m) {
    const arr = [...m.values()]
    arr.sort((a, b) => (a.is_dir === b.is_dir ? a.name.localeCompare(b.name) : a.is_dir ? -1 : 1))
    return arr
  }
  function materialize(m) {
    const arr = sortMap(m)
    for (const n of arr) {
      if (n.children instanceof Map) n.children = materialize(n.children)
      else if (n.is_dir) n.children = []
    }
    return arr
  }
  return materialize(rootChildren)
}

const fileTreeRows = computed(() => {
  // 把 fileTree 扁平化（按展开状态）成带 depth 的行
  const rows = []
  function walk(nodes, depth) {
    if (!Array.isArray(nodes)) return
    for (const n of nodes) {
      rows.push({ node: n, depth })
      const exp = expandedDirs.value && typeof expandedDirs.value === 'object' ? expandedDirs.value[n.rel] : false
      if (n.is_dir && exp && Array.isArray(n.children) && n.children.length) {
        walk(n.children, depth + 1)
      }
    }
  }
  walk(Array.isArray(fileTree.value) ? fileTree.value : [], 0)
  return rows
})

function formatSize(bytes) {
  if (!bytes || bytes < 0) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024 / 1024 / 1024).toFixed(1) + ' GB'
}

function fileGlyph(node) {
  if (node.is_dir) return '📂'
  const n = node.name.toLowerCase()
  if (/\.(png|jpe?g|gif|svg|webp|bmp|ico)$/.test(n)) return '🖼'
  if (/\.(mp4|mov|avi|mkv|webm)$/.test(n)) return '🎬'
  if (/\.(mp3|wav|flac|ogg|m4a)$/.test(n)) return '🎵'
  if (/\.(zip|tar|gz|7z|rar)$/.test(n)) return '📦'
  if (/\.(pdf)$/.test(n)) return '📕'
  if (/\.(md|markdown|txt)$/.test(n)) return '📝'
  if (/\.(json|ya?ml|toml|ini|cfg|conf)$/.test(n)) return '⚙'
  if (/\.(css|scss|less)$/.test(n)) return '🎨'
  if (/\.(vue|jsx|tsx|svelte)$/.test(n)) return '🧩'
  if (/\.(html?)$/.test(n)) return '🔖'
  if (/\.(py|js|ts|java|c|cpp|go|rs|rb|php|sh|ps1|bat)$/.test(n)) return '📜'
  return '📄'
}

async function loadWorkspaceFiles() {
  filesLoading.value = true
  filesError.value = ''
  try {
    if (!currentWorkspaceId.value) {
      const resW = await fetch('/api/workspaces')
      if (!resW.ok) throw new Error('无法获取工作空间列表')
      const dataW = await resW.json()
      currentWorkspaceId.value = dataW.current_id || ''
    }
    if (!currentWorkspaceId.value) {
      fileTree.value = []
      wsName.value = ''
      wsPath.value = ''
      return
    }
    const res = await fetch(`/api/workspaces/${currentWorkspaceId.value}/files?max_depth=6&max_files=5000`)
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.error || `HTTP ${res.status}`)
    }
    const data = await res.json()
    fileTree.value = buildTreeFromFlat(data.files || [])
    // 同时拉详情拿 workspace 名字
    const wsRes = await fetch('/api/workspaces')
    if (wsRes.ok) {
      const wd = await wsRes.json()
      const ws = (wd.workspaces || []).find(w => w.id === currentWorkspaceId.value)
      if (ws) {
        wsName.value = ws.name
        wsPath.value = ws.path
      }
    }
  } catch (e) {
    filesError.value = e.message || String(e)
  } finally {
    filesLoading.value = false
  }
}

function onFileRowClick(node) {
  if (node.is_dir) {
    const next = { ...expandedDirs.value }
    if (next[node.rel]) delete next[node.rel]
    else next[node.rel] = true
    expandedDirs.value = next
  } else {
    onFilePick(node)
  }
}

function onFilePick(node) {
  // 把文件相对路径附到输入框，作为给 AI 的上下文
  const ref = '@' + node.rel
  const cur = inputText.value.trim()
  if (cur.includes(ref)) {
    inputText.value = cur + '\n' + ref
  } else {
    inputText.value = cur ? cur + '  ' + ref : ref
  }
  // 简单提示
  showMessage(`已引用：${node.rel}`)
}
</script>

<style scoped>
.skill-picker-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex; align-items: center; justify-content: center;
  padding: 16px;
}
.skill-picker-modal {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  width: 100%; max-width: 480px;
  max-height: 85vh;
  display: flex; flex-direction: column;
  box-shadow: var(--shadow);
}
.skill-picker-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 20px 12px;
  border-bottom: 1px solid var(--border);
}
.skill-picker-title { font-size: 16px; font-weight: 700; }
.skill-picker-close {
  background: none; border: none; color: var(--text-muted);
  font-size: 18px; cursor: pointer; padding: 4px 8px; border-radius: 6px;
}
.skill-picker-close:hover { background: var(--bg-soft); color: var(--text); }
.skill-picker-sub { font-size: 12.5px; color: var(--text-muted); padding: 8px 20px 12px; }
.skill-picker-body { flex: 1; overflow-y: auto; padding: 8px 20px; }
.skill-picker-empty { text-align: center; padding: 30px; color: var(--text-muted); font-size: 13px; }
.skill-picker-item {
  display: flex; align-items: center; gap: 12px;
  padding: 12px; border-radius: var(--radius-sm);
  cursor: pointer; transition: all .15s;
  border: 1px solid transparent;
  margin-bottom: 6px;
}
.skill-picker-item:hover { background: var(--bg-soft); }
.skill-picker-item.selected {
  background: rgba(59, 130, 246, 0.08);
  border-color: rgba(59, 130, 246, 0.3);
}
.skill-picker-item.disabled { opacity: .45; cursor: not-allowed; }
.skill-picker-check {
  width: 20px; height: 20px; border-radius: 6px; flex-shrink: 0;
  border: 2px solid var(--border-strong);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; color: var(--primary);
}
.skill-picker-item.selected .skill-picker-check {
  background: var(--primary); border-color: var(--primary); color: #fff;
}
.skill-picker-icon {
  width: 36px; height: 36px; border-radius: 9px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; font-size: 18px;
}
.skill-picker-info { flex: 1; min-width: 0; }
.skill-picker-name { font-size: 13.5px; font-weight: 600; margin-bottom: 2px; }
.skill-picker-desc { font-size: 11.5px; color: var(--text-muted); line-height: 1.4; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.skill-picker-disabled { font-size: 10px; color: var(--text-muted); background: var(--bg-soft); padding: 2px 8px; border-radius: 4px; flex-shrink: 0; }
.skill-picker-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px; border-top: 1px solid var(--border);
}
.skill-picker-count { font-size: 12.5px; color: var(--text-muted); }

.chat-area-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.chat-area-head-left { flex: 1; min-width: 0; }
.chat-area-head-right { display: flex; gap: 6px; flex-shrink: 0; }

/* ===== 工作空间选择器（头部） ===== */
.ws-selector-wrap { position: relative; }
.ws-selector-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px 4px 6px; border-radius: 20px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.2);
  cursor: pointer; user-select: none;
  transition: border-color .15s, box-shadow .15s;
  font-family: inherit; font-size: 13px; color: var(--text);
}
.ws-selector-btn:hover { border-color: rgba(16, 185, 129, 0.5); box-shadow: 0 0 8px rgba(16, 185, 129, 0.15); }
.ws-selector-btn.open { border-color: rgba(16, 185, 129, 0.6); box-shadow: 0 0 10px rgba(16, 185, 129, 0.2); }
.ws-icon { font-size: 14px; }
.ws-name { font-weight: 500; max-width: 120px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ws-arrow { font-size: 10px; color: var(--text-muted); transition: transform .15s; }
.ws-selector-btn.open .ws-arrow { transform: rotate(180deg); }

.ws-dropdown {
  position: absolute; top: calc(100% + 4px); right: 0;
  width: 260px; background: var(--panel);
  border: 1px solid var(--border); border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
  z-index: 100; overflow: hidden;
  opacity: 0; transform: translateY(-6px); pointer-events: none;
  transition: all .15s;
}
.ws-dropdown.open { opacity: 1; transform: translateY(0); pointer-events: auto; }
.ws-search { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border); }
.ws-search input { flex: 1; border: none; outline: none; font-size: 13px; font-family: inherit; background: transparent; color: var(--text); }
.ws-search-icon { font-size: 12px; opacity: .55; flex-shrink: 0; }
.ws-list { max-height: 240px; overflow-y: auto; padding: 6px; }
.ws-item { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 8px; cursor: pointer; }
.ws-item:hover { background: rgba(16, 185, 129, 0.08); }
.ws-item.selected { background: rgba(16, 185, 129, 0.12); }
.ws-item-icon { font-size: 14px; opacity: .8; flex-shrink: 0; }
.ws-item-info { flex: 1; min-width: 0; }
.ws-item-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ws-item-check { font-size: 13px; font-weight: 700; color: var(--success); flex-shrink: 0; margin-left: 4px; }
.ws-item-actions button { background: transparent; border: none; color: var(--text-muted); cursor: pointer; font-size: 12px; padding: 2px 4px; }
.ws-item-actions button:hover { color: var(--danger); }
.ws-empty { padding: 14px; text-align: center; font-size: 12px; color: var(--text-muted); }
.ws-dropdown-actions { padding: 10px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; }
.ws-action-open,
.ws-action-none {
  width: 100%; padding: 8px; border: 1px dashed var(--border-strong);
  background: transparent; border-radius: 6px; color: var(--text-secondary);
  font-size: 12px; cursor: pointer; display: flex; align-items: center;
  justify-content: flex-start; gap: 6px; transition: all .12s;
  font-family: inherit;
}
.ws-action-open:hover { border-color: var(--primary); color: var(--primary); }
.ws-action-none:hover { border-color: var(--danger); color: var(--danger); }

.chat-area-skills { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; align-items: center; }
.chat-skill-tag {
  font-size: 11px; padding: 2px 8px; border-radius: 6px;
  background: rgba(59, 130, 246, 0.1); color: var(--primary);
  border: 1px solid rgba(59, 130, 246, 0.2);
}
.chat-skill-edit { background: none; border: none; cursor: pointer; font-size: 12px; padding: 2px 4px; opacity: .6; }
.chat-skill-edit:hover { opacity: 1; }
.chat-session-skills { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; }
.session-skill-chip { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(139, 92, 246, 0.1); color: var(--text-secondary); }

/* ===== 会话中心 · 当前模型指示器（可点击切换） ===== */
.chat-current-model-wrap { position: relative; }
.chat-current-model {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 4px 12px 4px 4px; border-radius: 24px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.18);
  cursor: pointer; user-select: none;
  transition: border-color .15s, box-shadow .15s;
}
.chat-current-model:hover { border-color: var(--primary); box-shadow: 0 0 10px rgba(59, 130, 246, 0.18); }
.chat-current-model-wrap.open .chat-current-model {
  border-color: var(--primary); box-shadow: 0 0 12px rgba(59, 130, 246, 0.22);
}
.chat-current-model-dot {
  width: 26px; height: 26px; border-radius: 50%;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 12px; flex-shrink: 0;
}
.chat-current-model-text { display: flex; flex-direction: column; line-height: 1.2; }
.chat-current-model-name { font-size: 12px; font-weight: 600; color: var(--text); }
.chat-current-model-sub { font-size: 10.5px; color: var(--text-muted); }
.chat-current-model-arrow { font-size: 10px; color: var(--text-muted); margin-left: 2px; transition: transform .15s; }
.chat-current-model-wrap.open .chat-current-model-arrow { transform: rotate(180deg); }

.chat-model-menu {
  position: absolute; top: calc(100% + 8px); right: 0;
  min-width: 320px; max-width: 380px;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: 0 12px 36px rgba(0, 0, 0, 0.32);
  padding: 8px; z-index: 200; display: none;
  backdrop-filter: blur(8px);
}
.chat-current-model-wrap.open .chat-model-menu {
  display: block; animation: chatModelMenuFadeIn .12s ease-out;
}
@keyframes chatModelMenuFadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.chat-model-menu-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 10px 8px; font-size: 12px; color: var(--text-muted);
  border-bottom: 1px solid var(--border); margin-bottom: 6px;
}
.chat-model-menu-link {
  background: none; border: none; color: var(--primary); cursor: pointer;
  font-size: 12px; padding: 0;
}
.chat-model-menu-link:hover { text-decoration: underline; }
.chat-model-menu-empty {
  padding: 18px 14px; text-align: center; font-size: 13px; color: var(--text-muted);
}
.chat-model-menu-list { display: flex; flex-direction: column; gap: 2px; max-height: 360px; overflow-y: auto; }
.chat-model-menu-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; border-radius: 8px; cursor: pointer;
  transition: background .12s;
}
.chat-model-menu-item:hover { background: rgba(59, 130, 246, 0.08); }
.chat-model-menu-item.active { background: rgba(59, 130, 246, 0.14); }
.chat-model-menu-dot {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 12px;
}
.chat-model-menu-info { flex: 1; min-width: 0; }
.chat-model-menu-name {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 600; color: var(--text);
}
.chat-model-menu-tag {
  font-size: 10px; padding: 1px 7px; border-radius: 10px;
  background: rgba(34, 197, 94, 0.15); color: #22c55e; font-weight: 600;
}
.chat-model-menu-sub {
  font-size: 11px; color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.chat-model-menu-check { color: #22c55e; font-weight: 700; font-size: 14px; }

.chat-session-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; align-items: center; }
/* 会话记忆开关图标：开=高亮，关=置灰；可点击切换 */
.session-memory-icon {
  display: inline-block;
  margin-left: 6px;
  padding: 0;
  border: none;
  background: transparent;
  font-size: 11px;
  line-height: 1;
  opacity: .35;
  filter: grayscale(1);
  vertical-align: -1px;
  cursor: pointer;
  transition: opacity .15s, transform .15s;
}
.session-memory-icon:hover {
  transform: scale(1.15);
}
.session-memory-icon.on {
  opacity: 1;
  filter: none;
}
.chat-session-model-chip {
  font-size: 10px; padding: 1px 7px; border-radius: 10px;
  background: rgba(59, 130, 246, 0.1); color: var(--primary);
  border: 1px solid rgba(59, 130, 246, 0.2); font-weight: 600;
  max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* ===== 右侧 · 工作空间文件面板 ===== */
.chat-files {
  flex-shrink: 0;
  border-left: 1px solid var(--border);
  background: var(--panel);
  display: flex; flex-direction: column;
  transition: width .18s ease;
  min-height: 0;
}
.chat-files.collapsed { width: 36px; }
.chat-files-head {
  display: flex; align-items: center;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-soft);
  flex-shrink: 0;
  overflow: visible;
}
.chat-files.collapsed .chat-files-head { padding: 10px 8px; justify-content: center; }
.chat-files-title-row {
  display: flex; align-items: center; justify-content: space-between;
  width: 100%; min-width: 0;
  gap: 8px;
  overflow: visible;
}
.chat-files-title {
  display: flex; align-items: center; gap: 6px;
  user-select: none;
  min-width: 0;
}
.chat-files-icon { font-size: 14px; flex-shrink: 0; }
.chat-files-sep { color: var(--text-muted); font-size: 14px; line-height: 1; }
.chat-files-name {
  font-size: 12.5px; font-weight: 600; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.chat-files.collapsed .chat-files-sep,
.chat-files.collapsed .chat-files-name,
.chat-files.collapsed .chat-files-arrow { display: none; }
.chat-files.collapsed .ws-picker { display: none; }
.chat-files-arrow { color: var(--text-muted); font-size: 10px; flex-shrink: 0; }
.chat-files-actions { display: flex; gap: 4px; flex-shrink: 0; align-items: center; }
.chat-files.collapsed .chat-files-actions { display: none; }
.chat-files-refresh {
  background: transparent; border: 1px solid var(--border);
  color: var(--text-muted); cursor: pointer;
  width: 22px; height: 22px; border-radius: 5px;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; padding: 0; line-height: 1;
}

/* ===== 工作空间选择器 ===== */
.ws-picker {
  position: relative;
  display: inline-flex;
  overflow: visible;
  font-family: inherit;
}
.ws-picker-trigger {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 10px 5px 8px;
  border: 1px solid var(--border, rgba(100, 116, 139, .25));
  border-radius: 9px;
  background: linear-gradient(180deg, rgba(255,255,255,.03), rgba(255,255,255,0)) , var(--bg);
  cursor: pointer;
  max-width: 220px;
  transition: border-color .18s ease, background .18s ease, box-shadow .18s ease, transform .12s ease;
  user-select: none;
  box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
}
.ws-picker-trigger:hover {
  border-color: color-mix(in srgb, var(--accent, #8b5cf6) 55%, var(--border));
  background: var(--bg-soft);
  box-shadow: 0 2px 8px rgba(139, 92, 246, .12);
}
.ws-picker-trigger:active { transform: translateY(1px); }
.ws-picker-trigger-icon {
  flex-shrink: 0;
  width: 14px; height: 14px;
  filter: drop-shadow(0 1px 0 rgba(255,255,255,.4));
}
.ws-picker-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text, #0f172a);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 150px;
  line-height: 1;
  letter-spacing: .1px;
}
.ws-picker-arrow {
  flex-shrink: 0;
  color: var(--text-muted, #64748b);
  transition: transform .2s ease, color .2s ease;
}
.ws-picker.open .ws-picker-trigger {
  border-color: var(--accent, #8b5cf6);
  background: color-mix(in srgb, var(--accent) 8%, var(--bg));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent),
              0 2px 8px rgba(139, 92, 246, .18);
}
.ws-picker.open .ws-picker-arrow {
  transform: rotate(180deg);
  color: var(--accent);
}
.ws-picker-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 999;
  min-width: 230px;
  max-width: 280px;
  background: var(--bg, #ffffff);
  border: 1px solid color-mix(in srgb, var(--border) 85%, var(--accent) 15%);
  border-radius: 14px;
  box-shadow:
    0 8px 24px rgba(15, 23, 42, .08),
    0 20px 48px rgba(15, 23, 42, .10),
    0 0 0 1px rgba(255, 255, 255, .2) inset;
  overflow: hidden;
  backdrop-filter: blur(10px);
  animation: wsPop .18s cubic-bezier(.2,.9,.3,1.1);
  transform-origin: top right;
}
@keyframes wsPop {
  from { opacity: 0; transform: translateY(-4px) scale(.98); }
  to   { opacity: 1; transform: translateY(0)    scale(1);    }
}
.ws-picker-header {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px 9px;
  background:
    linear-gradient(180deg,
      color-mix(in srgb, var(--accent, #8b5cf6) 10%, transparent),
      transparent 70%);
  border-bottom: 1px solid var(--border);
}
.ws-picker-header-icon {
  width: 28px; height: 28px; flex-shrink: 0;
  display: grid; place-items: center;
  background: color-mix(in srgb, var(--accent, #8b5cf6) 14%, transparent);
  border-radius: 8px;
  font-size: 14px;
}
.ws-picker-header-text { min-width: 0; }
.ws-picker-header-title {
  font-size: 12.5px; font-weight: 700; color: var(--text);
  line-height: 1.15;
  letter-spacing: .2px;
}
.ws-picker-header-sub {
  font-size: 10.5px; color: var(--text-muted, #64748b);
  line-height: 1.3; margin-top: 2px;
}
.ws-picker-list {
  max-height: 220px;
  overflow-y: auto;
  padding: 6px;
}
.ws-picker-list::-webkit-scrollbar { width: 6px; }
.ws-picker-list::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--border) 90%, var(--text-muted));
  border-radius: 3px;
}
.ws-picker-list::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}
.ws-picker-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 9px;
  margin: 1px 0;
  border-radius: 9px;
  cursor: pointer;
  color: var(--text, #0f172a);
  transition: background .12s ease, color .12s ease, transform .08s ease;
}
.ws-picker-item:hover {
  background: var(--bg-soft, #f1f5f9);
}
.ws-picker-item:active { transform: scale(.992); }
.ws-picker-item.selected {
  background: color-mix(in srgb, var(--accent, #8b5cf6) 14%, transparent);
  color: var(--accent, #7c3aed);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 30%, transparent);
}
.ws-picker-item-left {
  display: flex; align-items: center; gap: 7px;
  min-width: 0;
}
.ws-picker-item-check {
  flex-shrink: 0;
  color: var(--accent, #7c3aed);
}
.ws-picker-item-icon {
  font-size: 12.5px; flex-shrink: 0;
  filter: saturate(.9);
}
.ws-picker-item-name {
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 150px;
  line-height: 1;
}
.ws-picker-item.selected .ws-picker-item-name { font-weight: 600; }
.ws-picker-item-del {
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-muted, #94a3b8);
  cursor: pointer;
  padding: 4px 5px;
  border-radius: 7px;
  display: inline-flex; align-items: center; justify-content: center;
  opacity: 0;
  transform: translateX(2px);
  transition: opacity .15s ease, color .15s ease, background .15s ease, border-color .15s ease, transform .15s ease;
}
.ws-picker-item:hover .ws-picker-item-del,
.ws-picker-item.selected .ws-picker-item-del { opacity: 1; transform: translateX(0); }
.ws-picker-item-del:hover {
  color: #ef4444;
  background: rgba(239, 68, 68, .09);
  border-color: rgba(239, 68, 68, .25);
}
.ws-picker-empty {
  padding: 18px 16px 20px;
  text-align: center;
  color: var(--text-muted, #64748b);
  font-size: 12px;
  line-height: 1.5;
}
.ws-picker-actions {
  padding: 8px;
  border-top: 1px solid var(--border);
  background: linear-gradient(0deg, var(--bg-soft, #f8fafc), transparent);
}
.ws-picker-btn-create {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  width: 100%;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px dashed color-mix(in srgb, var(--accent, #8b5cf6) 45%, var(--border));
  background: color-mix(in srgb, var(--accent, #8b5cf6) 6%, transparent);
  color: var(--accent, #7c3aed);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background .15s ease, border-color .15s ease, transform .1s ease;
}
.ws-picker-btn-create:hover {
  background: color-mix(in srgb, var(--accent, #8b5cf6) 12%, transparent);
  border-color: var(--accent);
  border-style: solid;
}
.ws-picker-btn-create:active { transform: scale(.99); }
.chat-files-refresh:hover { color: var(--primary); border-color: var(--primary); }

.chat-files-body { flex: 1; overflow-y: auto; padding: 4px 0; min-height: 0; }
.chat-files.collapsed .chat-files-body { display: none; }
.chat-files-empty {
  padding: 20px 16px; text-align: center; color: var(--text-muted);
  font-size: 12px; line-height: 1.5;
}
.chat-files-error { color: #ef4444; }

.chat-files-tree { display: flex; flex-direction: column; }
.chat-files-row {
  display: flex; align-items: center; gap: 4px;
  padding: 4px 8px 4px 0;
  font-size: 12.5px; color: var(--text);
  cursor: pointer; user-select: none;
  white-space: nowrap;
  transition: background .1s;
}
.chat-files-row:hover { background: var(--bg-soft); }
.chat-files-row.expanded { color: var(--primary); }
.chat-files-toggle {
  width: 12px; flex-shrink: 0; text-align: center;
  color: var(--text-muted); font-size: 9px; line-height: 1;
}
.chat-files-glyph { flex-shrink: 0; font-size: 13px; line-height: 1; }
.chat-files-label {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
}
.chat-files-size {
  flex-shrink: 0; color: var(--text-muted); font-size: 10.5px;
  margin-left: auto; padding-left: 8px;
}

/* ===== 图片上传 ===== */
.chat-input-area {
  flex-direction: column;
  gap: 8px;
}
/* ===== 知识库选择条 ===== */
.chat-kb-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 4px 0;
}
.chat-kb-label {
  font-size: 11.5px;
  color: var(--text-muted);
  flex-shrink: 0;
}
.chat-kb-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--bg-soft);
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all .15s;
  user-select: none;
}
.chat-kb-chip:hover {
  border-color: var(--primary);
}
.chat-kb-chip input {
  accent-color: var(--primary);
  margin: 0;
  cursor: pointer;
}
.chat-kb-chip-name {
  white-space: nowrap;
}
.chat-kb-chip-count {
  font-size: 10.5px;
  color: var(--text-muted);
  background: var(--panel);
  border-radius: 8px;
  padding: 0 5px;
}
.chat-kb-chip:has(input:checked) {
  border-color: var(--primary);
  background: rgba(59, 130, 246, 0.12);
  color: var(--primary);
}
.chat-input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}
.chat-upload {
  flex-shrink: 0;
  width: 44px; height: 44px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg-soft);
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: color .15s, border-color .15s, background .15s;
}
.chat-upload:hover {
  color: var(--primary);
  border-color: var(--primary);
  background: rgba(59, 130, 246, 0.08);
}
.chat-input-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chat-input-image-item {
  position: relative;
}
.chat-input-image-item img {
  width: 56px; height: 56px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--border);
  display: block;
}
.chat-input-row textarea {
  flex: 1;
  min-height: 68px;
  max-height: 240px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-soft);
  color: var(--text);
  font-size: 14px;
  line-height: 22px;
  resize: none;
  outline: none;
  transition: border-color .2s, background .2s;
  font-family: inherit;
  box-sizing: border-box;
  overflow-y: hidden;
}
.chat-input-row textarea:focus {
  border-color: var(--primary);
  background: var(--bg-card);
}
.chat-input-row textarea::placeholder {
  color: var(--text-muted);
}
.chat-input-image-del {
  position: absolute;
  top: -6px; right: -6px;
  width: 18px; height: 18px;
  border-radius: 50%;
  border: none;
  background: rgba(15, 23, 42, 0.85);
  color: #fff;
  font-size: 10px;
  line-height: 1;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.chat-msg-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
}
.chat-msg-image {
  max-width: 180px;
  max-height: 180px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--border);
  cursor: zoom-in;
}

/* ===== Agent 模式 ===== */
.chat-send.agent-active {
  background: linear-gradient(135deg, #8b5cf6, #6d28d9) !important;
}

.chat-agent-steps {
  margin-top: 8px; padding: 10px;
  background: rgba(139, 92, 246, 0.06);
  border: 1px solid rgba(139, 92, 246, 0.15);
  border-radius: 8px;
  display: flex; flex-direction: column; gap: 4px;
}
.chat-agent-steps-title {
  font-size: 11px; font-weight: 600; color: #8b5cf6;
  margin-bottom: 2px;
}

/* ===== 思考过程（合并进报告卡片内的内联区域） ===== */
.chat-thinking-inline {
  margin: 4px 0 12px;
  border-radius: 8px;
  background: rgba(139, 92, 246, 0.04);
  border: 1px solid rgba(139, 92, 246, 0.12);
  overflow: hidden;
}
.chat-thinking-inline-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 10px;
  cursor: pointer;
  user-select: none;
  font-size: 12.5px;
  transition: background .15s;
}
.chat-thinking-inline-header:hover {
  background: rgba(139, 92, 246, 0.06);
}
.chat-thinking-inline-icon {
  font-size: 14px;
  flex-shrink: 0;
}
.chat-thinking-inline-title {
  flex: 1;
  font-weight: 600;
  color: var(--text-secondary);
}
.chat-thinking-inline-title.active {
  color: #8b5cf6;
}
.chat-thinking-duration {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
  margin-left: 6px;
}
.chat-thinking-inline-body {
  border-top: 1px solid rgba(139, 92, 246, 0.1);
}

/* ===== 时间线（思考+命令+结果） ===== */
.chat-timeline {
  padding: 4px 0;
  position: relative;
}
.chat-timeline-item {
  position: relative;
  padding: 0 0 2px 26px;
}
.chat-timeline-item::before {
  content: '';
  position: absolute;
  left: 10px;
  top: 18px;
  bottom: -2px;
  width: 1.5px;
  background: linear-gradient(to bottom, rgba(139, 92, 246, 0.3), rgba(139, 92, 246, 0.05));
}
.chat-timeline-item:last-child::before {
  display: none;
}
.timeline-icon {
  font-size: 13px;
  flex-shrink: 0;
  width: 16px;
  text-align: center;
}
.timeline-thinking-header,
.timeline-command-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 10px;
  cursor: pointer;
  border-radius: 6px;
  transition: background .15s;
  font-size: 12.5px;
}
.timeline-thinking-header:hover,
.timeline-command-header:hover {
  background: rgba(139, 92, 246, 0.07);
}
.timeline-label {
  color: var(--text-secondary);
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}
.timeline-command-name {
  color: var(--text);
  font-weight: 600;
  margin-left: auto;
  padding: 1px 8px;
  border-radius: 4px;
  background: rgba(139, 92, 246, 0.1);
  font-size: 11.5px;
  font-family: 'Cascadia Code', Consolas, monospace;
}
.timeline-elapsed {
  color: var(--text-muted);
  font-size: 11px;
  white-space: nowrap;
  flex-shrink: 0;
}
.timeline-arrow {
  font-size: 9px;
  color: var(--text-muted);
  transition: transform .18s ease;
  flex-shrink: 0;
}
.timeline-arrow.expanded {
  transform: rotate(90deg);
}
.timeline-thinking-content {
  margin: 0 10px 8px 33px;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-secondary);
  background: rgba(139, 92, 246, 0.05);
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
}
.timeline-command-result {
  margin: 0 10px 8px 33px;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.timeline-command-result pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 11.5px;
  max-height: 220px;
  overflow-y: auto;
}

/* ===== 思考过程（任务运行初期独立卡片） ===== */
.chat-thinking-card {
  background: rgba(139, 92, 246, 0.04);
  border: 1px solid rgba(139, 92, 246, 0.15);
  border-radius: 10px;
  margin-bottom: 10px;
  overflow: hidden;
  animation: thinkingFadeIn .3s ease-out;
}
@keyframes thinkingFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
.chat-thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  transition: background .15s;
}
.chat-thinking-header:hover {
  background: rgba(139, 92, 246, 0.06);
}
.chat-thinking-icon {
  font-size: 16px;
  flex-shrink: 0;
}
.chat-thinking-status {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  flex: 1;
}
.chat-thinking-status.active {
  color: #8b5cf6;
}
.chat-thinking-arrow {
  font-size: 10px;
  color: var(--text-muted);
  transition: transform .2s ease;
  flex-shrink: 0;
}
.chat-thinking-arrow.expanded {
  transform: rotate(180deg);
}
.chat-thinking-body {
  border-top: 1px solid rgba(139, 92, 246, 0.1);
}
.thinking-dots span {
  animation: thinkingBlink 1.4s infinite;
  font-weight: bold;
  font-size: 18px;
}
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes thinkingBlink {
  0%, 80%, 100% { opacity: 0.2; }
  40% { opacity: 1; }
}

.chat-report-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  width: 100%;
  max-width: 100%;
  animation: reportCardIn .25s ease-out;
  box-sizing: border-box;
  position: relative;
  overflow: hidden;
}
.chat-report-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, var(--primary), var(--purple), var(--accent));
  opacity: .8;
}
@keyframes reportCardIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.chat-report-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px;
  gap: 8px;
}
.chat-report-collapse-arrow {
  font-size: 10px;
  color: var(--text-muted);
  transition: transform .2s ease;
  flex-shrink: 0;
}
.chat-report-collapse-arrow.expanded {
  transform: rotate(180deg);
}
.chat-report-body {
  animation: reportCardIn .2s ease-out;
}
.chat-report-badge {
  font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 20px;
}
.chat-report-badge.running {
  background: rgba(59, 130, 246, 0.12); color: var(--primary);
}
.chat-report-badge.completed {
  background: rgba(34, 197, 94, 0.12); color: #22c55e;
}
.chat-report-duration {
  font-size: 11px; color: var(--text-muted);
  cursor: pointer;
  padding: 2px 6px; border-radius: 4px;
  transition: background .12s, color .12s;
}
.chat-report-duration-toggle {
  font-size: 11px; color: var(--text-muted);
  cursor: pointer;
  padding: 3px 8px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: background .12s, color .12s;
  user-select: none;
}
.chat-report-duration-toggle:hover {
  background: rgba(139, 92, 246, 0.08);
  color: var(--primary);
}
.chat-report-duration-toggle.expanded {
  color: var(--primary);
}
.chat-report-duration:hover {
  background: rgba(139, 92, 246, 0.08);
  color: var(--primary);
}
.chat-report-duration.expanded {
  color: var(--primary);
}
.chat-report-title {
  font-size: 15px; font-weight: 700; color: var(--text);
  margin-bottom: 8px; line-height: 1.35;
}
.chat-report-summary {
  font-size: 12.5px; color: var(--text-secondary); line-height: 1.5;
  margin-bottom: 12px;
}
.chat-report-section {
  margin-top: 10px;
}
.chat-report-section-title {
  font-size: 12px; font-weight: 700; color: var(--text);
  margin-bottom: 6px;
  display: flex; align-items: center; gap: 6px;
  padding-left: 8px;
  border-left: 3px solid var(--primary);
}
.chat-report-section-body { overflow: hidden; }
.chat-report-list {
  margin: 0; padding: 0; list-style: none;
}
.chat-report-list li {
  font-size: 12px; color: var(--text-secondary); line-height: 1.7;
  padding: 4px 0 4px 16px; position: relative;
}
.chat-report-list li::before {
  content: ''; position: absolute; left: 3px; top: 10px;
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--primary); opacity: .7;
}
.chat-report-list li code {
  background: rgba(139, 92, 246, 0.1); padding: 1px 6px; border-radius: 4px;
  font-family: Consolas, 'Cascadia Code', monospace;
  font-size: 11.5px; color: var(--accent);
}
.chat-report-list li strong { color: var(--text); font-weight: 600; }
.chat-report-list li a { color: var(--primary); text-decoration: none; border-bottom: 1px solid rgba(59, 130, 246, 0.3); }
.chat-report-section-body :deep(.md-table-wrap) { margin: 10px 0; }
.chat-report-section-body :deep(table) { width: 100%; border-collapse: collapse; font-size: 12px; }
.chat-report-section-body :deep(th) {
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.18), rgba(59, 130, 246, 0.08));
  font-weight: 700; color: var(--text); text-align: left;
  padding: 8px 10px; border-bottom: 2px solid rgba(59, 130, 246, 0.3);
}
.chat-report-section-body :deep(td) {
  padding: 7px 10px; color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
}
.chat-report-section-body :deep(tr:last-child td) { border-bottom: none; }
.chat-report-section-body :deep(tr:hover td) { background: rgba(59, 130, 246, 0.04); }

.report-section-text.md {
  font-size: 13.5px;
  color: var(--text);
  line-height: 1.75;
}
.report-section-text.md p { margin: 0 0 12px 0; }
.report-section-text.md p:last-child { margin-bottom: 0; }
.report-section-text.md strong { color: var(--text); font-weight: 700; }
.report-section-text.md em { color: var(--text-secondary); font-style: italic; }
.report-section-text.md code {
  background: rgba(139, 92, 246, 0.1); padding: 2px 6px; border-radius: 5px;
  font-family: Consolas, 'Cascadia Code', monospace;
  font-size: 12.5px; color: var(--accent);
}
.report-section-text.md pre {
  background: #1e1e2e; color: #e0e0e0;
  padding: 14px 16px; border-radius: 10px;
  overflow-x: auto; font-size: 12.5px; line-height: 1.6;
  margin: 12px 0;
  white-space: pre;
  font-family: Consolas, 'Cascadia Code', 'Courier New', monospace;
}
.report-section-text.md pre code {
  background: transparent; padding: 0; color: inherit; font-size: inherit;
}
.report-section-text.md a {
  color: var(--primary); text-decoration: none;
  border-bottom: 1px solid rgba(59, 130, 246, 0.3);
}
.report-section-text.md a:hover { opacity: .85; }
.report-section-text.md ul, .report-section-text.md ol {
  margin: 10px 0; padding-left: 24px;
}
.report-section-text.md li { margin: 4px 0; line-height: 1.7; }
.report-section-text.md ul li::marker { color: var(--primary); }
.report-section-text.md ol li::marker { color: var(--primary); font-weight: 700; }
.report-section-text.md blockquote {
  margin: 12px 0; padding: 10px 14px;
  border-left: 3px solid var(--primary);
  background: rgba(139, 92, 246, 0.06);
  color: var(--text-secondary);
  border-radius: 0 6px 6px 0;
}
.report-section-text.md h1, .report-section-text.md h2, .report-section-text.md h3,
.report-section-text.md h4, .report-section-text.md h5, .report-section-text.md h6 {
  font-weight: 700; color: var(--text); margin: 16px 0 8px 0; line-height: 1.35;
}
.report-section-text.md h1 { font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.report-section-text.md h2 { font-size: 16px; border-bottom: 1px solid var(--border-light); padding-bottom: 4px; }
.report-section-text.md h3 { font-size: 14.5px; }
.report-section-text.md hr {
  border: none; border-top: 1px solid var(--border);
  margin: 16px 0;
}
.report-section-text.md .md-table-wrap { margin: 12px 0; overflow-x: auto; }
.report-section-text.md table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.report-section-text.md th {
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.18), rgba(59, 130, 246, 0.08));
  font-weight: 700; color: var(--text); text-align: left;
  padding: 9px 12px; border-bottom: 2px solid rgba(59, 130, 246, 0.3);
}
.report-section-text.md td {
  padding: 8px 12px; color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
}
.report-section-text.md tr:last-child td { border-bottom: none; }
.report-section-text.md tr:hover td { background: rgba(59, 130, 246, 0.04); }

/* ===== 报告卡片 · 可折叠执行步骤 ===== */
.chat-report-steps {
  display: flex; flex-direction: column; gap: 4px;
}
.chat-report-step {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-soft);
  overflow: hidden;
}
.chat-report-step.running {
  border-color: rgba(59, 130, 246, 0.35);
  background: rgba(59, 130, 246, 0.05);
}
.chat-report-step.error {
  border-color: rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.04);
}
.chat-report-step-header {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px;
  cursor: pointer;
  user-select: none;
  transition: background .12s;
}
.chat-report-step-header:hover { background: rgba(139, 92, 246, 0.06); }
.chat-report-step-icon { font-size: 13px; flex-shrink: 0; }
.chat-report-step-name {
  flex: 1; min-width: 0;
  font-size: 12px; font-weight: 500; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.chat-report-step-time {
  font-size: 10px; color: var(--text-muted); flex-shrink: 0;
}
.chat-report-step-toggle {
  font-size: 11px; color: var(--text-muted); flex-shrink: 0;
  width: 14px; text-align: center;
}
.chat-report-step-body {
  padding: 8px 10px;
  border-top: 1px solid var(--border);
  background: var(--card);
}
.chat-report-step-body pre {
  margin: 0;
  font-size: 11px; line-height: 1.45;
  color: var(--text-secondary);
  white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  max-height: 240px; overflow-y: auto;
}
.chat-report-step-collapse {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
  text-align: right;
}
.chat-report-step-collapse:hover { color: var(--primary); }
/* 运行中的步骤呼吸动画：提示正在执行 */
.chat-report-step.running .chat-report-step-icon,
.chat-report-step.running .chat-report-step-name {
  animation: chatStepPulse 1.2s ease-in-out infinite;
}
@keyframes chatStepPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .45; }
}
@media (prefers-reduced-motion: reduce) {
  .chat-report-step.running .chat-report-step-icon,
  .chat-report-step.running .chat-report-step-name { animation: none; }
}

</style>
