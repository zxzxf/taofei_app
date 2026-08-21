<template>
  <div class="task-layout">
    <div class="task-nav">
      <button class="task-nav-item" :class="{ active: section === 'input' }" @click="section = 'input'"><span>📝</span> 新建任务</button>
      <button class="task-nav-item" :class="{ active: section === 'tasklist' }" @click="switchToTaskList"><span>📋</span> 任务编排管理</button>
      <button class="task-nav-item" :class="{ active: section === 'result' }" @click="section = 'result'"><span>📄</span> 运行结果</button>
      <button class="task-nav-item" :class="{ active: section === 'flow' }" @click="section = 'flow'"><span>🧩</span> 可视化编排</button>
    </div>
    <div class="task-content">
      <!-- 新建任务 -->
      <div v-show="section === 'input'" class="task-panel active">
        <div class="hero-input">
          <h1>今天想让 AI 帮你做什么？</h1>
          <p>输入一个主题，研究员 Agent 负责调研，分析师 Agent 负责成稿</p>
          <div class="input-box">
            <input v-model="topic" type="text" placeholder="例如：网络安全态势感知技术，或 AI 智能体框架…" @keydown.enter="runTask">
            <button class="btn-run" @click="runTask">▶ 开始运行</button>
          </div>
        </div>
        <div class="card-title" style="margin-bottom:12px;">📌 推荐模板</div>
        <div class="template-grid">
          <div class="template-card" v-for="t in templates" :key="t.title" @click="onTemplateClick(t)">
            <div class="t-icon">{{ t.icon }}</div>
            <div class="t-title">{{ t.title }}</div>
            <div class="t-desc">{{ t.desc }}</div>
          </div>
        </div>
      </div>
      <!-- 任务编排管理 -->
      <div v-show="section === 'tasklist'" class="task-panel active">
        <div class="task-list-toolbar">
          <div class="task-search-box">
            <span class="task-search-icon">🔍</span>
            <input v-model="taskSearch" type="text" placeholder="搜索任务名称…" @input="onTaskSearch">
          </div>
          <div class="task-filter-group">
            <button class="task-filter-btn" :class="{ active: taskFilter === 'all' }" @click="taskFilter = 'all'; taskPage = 1">全部</button>
            <button class="task-filter-btn" :class="{ active: taskFilter === 'builtin' }" @click="taskFilter = 'builtin'; taskPage = 1">模板</button>
            <button class="task-filter-btn" :class="{ active: taskFilter === 'user' }" @click="taskFilter = 'user'; taskPage = 1">自定义</button>
          </div>
        </div>
        <div v-if="filteredFlows.length === 0" class="placeholder-card">
          <div class="big-icon">📭</div>
          <h3>{{ taskSearch ? '未找到匹配的任务' : '暂无保存的任务' }}</h3>
          <p>{{ taskSearch ? '试试其他关键词' : '在「可视化编排」中创建工作流后，点击「💾 保存」即可在此查看。' }}</p>
        </div>
        <div v-else class="saved-flow-list">
          <div v-for="f in pagedFlows" :key="f.name" class="saved-flow-card" :class="{ builtin: f.builtin }">
            <div class="saved-flow-icon">{{ f.icon || (f.nodeCount >= 3 ? '🧩' : '📝') }}</div>
            <div class="saved-flow-info">
              <div class="saved-flow-name">
                {{ f.name }}
                <span v-if="f.builtin" class="builtin-badge">模板</span>
              </div>
              <div class="saved-flow-meta">{{ f.nodeCount }} 个节点 · {{ f.connCount }} 条连线 · {{ f.savedAt }}</div>
            </div>
            <div class="saved-flow-ops">
              <button class="skill-op" @click="editSavedFlow(f.name)">✏️ 编辑</button>
              <button class="skill-op" @click="loadSavedFlow(f.name)">▶ 运行</button>
              <button v-if="!f.builtin" class="skill-op danger" @click="deleteSavedFlow(f.name)">🗑 删除</button>
            </div>
          </div>
        </div>
        <!-- 分页 -->
        <div v-if="filteredFlows.length > 0" class="skill-pagination">
          <button class="page-btn" :disabled="taskPage === 1" @click="taskPage--">‹</button>
          <button v-for="p in taskTotalPages" :key="p" class="page-num" :class="{ active: p === taskPage }" @click="taskPage = p">{{ p }}</button>
          <button class="page-btn" :disabled="taskPage === taskTotalPages" @click="taskPage++">›</button>
          <span class="page-info">{{ taskPage }}/{{ taskTotalPages }} 页 · {{ filteredFlows.length }} 条</span>
        </div>
      </div>
      <!-- 运行结果 -->
      <div v-show="section === 'result'" class="task-panel active">
        <div v-if="running" class="status-bar"><div class="spinner"></div><span>任务执行中…</span></div>
        <div v-if="error" class="error-box">{{ error }}</div>
        <!-- 工具栏 -->
        <div class="task-list-toolbar">
          <div class="task-search-box">
            <span class="task-search-icon">🔍</span>
            <input v-model="resultSearch" type="text" placeholder="搜索工作流名称或结果…" @input="onResultSearch">
          </div>
          <div class="task-filter-group">
            <button class="task-filter-btn" :class="{ active: !selectedResultId }" @click="selectedResultId = null">列表</button>
            <button v-if="resultList.length" class="task-filter-btn danger-btn" @click="clearAllResults">清空全部</button>
          </div>
        </div>
        <!-- 列表视图 -->
        <template v-if="!selectedResultId">
          <div v-if="filteredResults.length === 0" class="placeholder-card">
            <div class="big-icon">📊</div>
            <h3>{{ resultSearch ? '未找到匹配的结果' : '暂无运行结果' }}</h3>
            <p>{{ resultSearch ? '试试其他关键词' : '在「可视化编排」中运行工作流后，结果将自动保存到此列表。' }}</p>
          </div>
          <div v-else class="saved-flow-list">
            <div v-for="r in pagedResults" :key="r.id" class="saved-flow-card" :class="{ error: r.status === 'error' }" @click="selectedResultId = r.id" style="cursor:pointer;">
              <div class="saved-flow-icon">{{ r.status === 'error' ? '❌' : '✅' }}</div>
              <div class="saved-flow-info">
                <div class="saved-flow-name">{{ r.flowName }}</div>
                <div class="saved-flow-meta">{{ r.nodeCount }} 个节点 · {{ r.duration }}ms · {{ r.executedAt }}</div>
              </div>
              <div class="saved-flow-ops">
                <button class="skill-op" @click.stop="selectedResultId = r.id">📄 查看</button>
                <button class="skill-op" @click.stop="copyResultItem(r)">📋 复制</button>
                <button class="skill-op danger" @click.stop="deleteResult(r.id)">🗑 删除</button>
              </div>
            </div>
          </div>
          <!-- 分页 -->
          <div v-if="filteredResults.length > 0" class="skill-pagination">
            <button class="page-btn" :disabled="resultPage === 1" @click="resultPage--">‹</button>
            <button v-for="p in resultTotalPages" :key="p" class="page-num" :class="{ active: p === resultPage }" @click="resultPage = p">{{ p }}</button>
            <button class="page-btn" :disabled="resultPage === resultTotalPages" @click="resultPage++">›</button>
            <span class="page-info">{{ resultPage }}/{{ resultTotalPages }} 页 · {{ filteredResults.length }} 条</span>
          </div>
        </template>
        <!-- 详情视图 -->
        <template v-else-if="selectedResult">
          <div class="result-card" style="margin-top:18px;">
            <div class="result-head">
              <span style="font-weight:700;font-size:15px;">🧩 {{ selectedResult.flowName }}</span>
              <div style="display:flex;gap:8px;">
                <button class="btn-copy" @click="copyResultItem(selectedResult)">复制结果</button>
                <button class="btn-copy" @click="selectedResultId = null">← 返回列表</button>
              </div>
            </div>
            <div style="display:flex;gap:16px;margin:8px 0 4px;font-size:12px;color:var(--text-muted);">
              <span>{{ selectedResult.status === 'error' ? '❌ 执行失败' : '✅ 执行成功' }}</span>
              <span>· {{ selectedResult.nodeCount }} 个节点</span>
              <span>· {{ selectedResult.duration }}ms</span>
              <span>· {{ selectedResult.executedAt }}</span>
            </div>
            <pre class="flow-result-text">{{ selectedResult.result }}</pre>
          </div>
        </template>
      </div>
      <!-- 可视化编排 -->
      <div v-show="section === 'flow'" class="task-panel active">
        <div class="flow-toolbar">
          <input v-model="flowName" type="text" placeholder="工作流名称" class="flow-name-input">
          <button class="btn-mini" @click="saveFlow">💾 保存</button>
          <button class="btn-mini" @click="loadFlow">📂 加载</button>
          <button class="btn-mini" @click="exportFlow">📤 导出</button>
          <button class="btn-mini" @click="importFlow">📥 导入</button>
          <input ref="importInput" type="file" accept=".json" style="display:none" @change="onImportFile">
          <button class="btn-mini run" @click="runFlow">▶ 调试运行</button>
          <button class="btn-mini" :class="{ run: true, active: wfRunning }" @click="runFlowBackend" :disabled="wfRunning">
            {{ wfRunning ? '⏳ 执行中...' : '🚀 后端执行' }}
          </button>
          <button class="btn-mini debug" @click="stepRun" :disabled="debugState.isStepping && !debugState.stepQueue.length">⏭ 单步</button>
          <button class="btn-mini" @click="testSingleNode" :disabled="!selectedNodeData || selectedNodeData.type==='end'">🔍 测试节点</button>
          <button class="btn-mini" @click="toggleBreakpoint" :disabled="!selectedNodeData">🔴 断点</button>
          <button class="btn-mini" @click="autoArrange">⊞ 自动排列</button>
          <button class="btn-mini" @click="clearFlow">🗑 清空</button>
          <div class="flow-zoom">
            <button class="btn-mini" @click="zoomOut">−</button>
            <span class="zoom-label">{{ Math.round(zoom * 100) }}%</span>
            <button class="btn-mini" @click="zoomIn">+</button>
            <button class="btn-mini" @click="resetView">⌂</button>
          </div>
        </div>
        <div class="flow-wrap">
          <!-- 节点面板 -->
          <div class="flow-palette">
            <div class="flow-palette-group">
              <div class="flow-palette-title">流程控制</div>
              <div class="flow-palette-item" v-for="pt in nodeTypes.slice(0,2)" :key="pt.type"
                   draggable="true" @dragstart="onPaletteDragStart($event, pt)" @click="addNode(pt)">
                <span class="flow-palette-icon" :style="{background:pt.color}">{{ pt.icon }}</span>
                <span>{{ pt.label }}</span>
              </div>
            </div>
            <div class="flow-palette-group">
              <div class="flow-palette-title">处理节点</div>
              <div class="flow-palette-item" v-for="pt in nodeTypes.slice(2,6)" :key="pt.type"
                   draggable="true" @dragstart="onPaletteDragStart($event, pt)" @click="addNode(pt)">
                <span class="flow-palette-icon" :style="{background:pt.color}">{{ pt.icon }}</span>
                <span>{{ pt.label }}</span>
              </div>
            </div>
            <div class="flow-palette-group">
              <div class="flow-palette-title">逻辑与工具</div>
              <div class="flow-palette-item" v-for="pt in nodeTypes.slice(6)" :key="pt.type"
                   draggable="true" @dragstart="onPaletteDragStart($event, pt)" @click="addNode(pt)">
                <span class="flow-palette-icon" :style="{background:pt.color}">{{ pt.icon }}</span>
                <span>{{ pt.label }}</span>
              </div>
            </div>
          </div>
          <!-- 画布 -->
          <div class="flow-canvas-box" :class="{ panning: isPanningActive, connecting: !!draggingConn, dragover: !!dragFromPalette }"
               @wheel="onWheel" @mousedown="onCanvasMouseDown"
               @dragover.prevent="onCanvasDragOver" @drop.prevent="onCanvasDrop" @dragleave="onCanvasDragLeave">
            <div v-if="!nodes.length" class="flow-empty">
              <div style="font-size:32px;opacity:.3;margin-bottom:8px">🧩</div>
              <div>画布为空，从左侧添加节点开始编排</div>
              <div style="font-size:11px;margin-top:4px;opacity:.6">先添加「开始」和「结束」节点，再拖拽端口连线</div>
            </div>
            <div class="flow-canvas-inner" :style="{ transform: `translate(${panX}px, ${panY}px) scale(${zoom})` }">
              <!-- 网格背景 -->
              <div class="flow-grid"></div>
              <!-- 连线 -->
              <svg class="flow-svg" :viewBox="`${flowViewBox.x} ${flowViewBox.y} ${flowViewBox.w} ${flowViewBox.h}`" :style="flowSvgStyle">
                <!-- 透明粗路径作为点击区域 -->
                <path v-for="(conn,i) in connections" :key="'hit'+i"
                  :d="bezierPath(conn)" class="flow-edge-hit"
                  @click.stop="selectEdge(i)" />
                <!-- 可见的连线 -->
                <path v-for="(conn,i) in connections" :key="i"
                  :d="bezierPath(conn)" class="flow-edge" :class="{selected: selectedEdge===i}"
                  @click.stop="selectEdge(i)" />
                <circle v-for="(conn,i) in connections" :key="'c'+i"
                  :cx="nodePortPos(conn.from,'out').x" :cy="nodePortPos(conn.from,'out').y" r="3" class="flow-edge-dot" />
                <circle v-for="(conn,i) in connections" :key="'c2'+i"
                  :cx="nodePortPos(conn.to,'in').x" :cy="nodePortPos(conn.to,'in').y" r="3" class="flow-edge-dot" />
                <path v-if="draggingConn" :d="dragPath" class="flow-edge dragging" />
              </svg>
              <!-- 节点 -->
              <div v-for="node in nodes" :key="node.id"
                :data-id="node.id"
                class="flow-node" :class="[node.type, {
                  selected: selectedNode===node.id,
                  running: node._status==='running',
                  done: node._status==='done',
                  error: node._status==='error',
                  'drop-target': connTargetId===node.id,
                  dragging: draggingNodeId===node.id
                }]"
                :style="{left:node.x+'px', top:node.y+'px', width:(nodeTypeMap[node.type]?.w || 200)+'px', height:(nodeTypeMap[node.type]?.h || 68)+'px'}"
                @mousedown.stop="onNodeMouseDown($event,node)" @click.stop="selectNode(node.id)">
                <div class="flow-node-header">
                  <span class="flow-node-icon" :style="{background:nodeColor(node.type)}">{{ node.icon }}</span>
                  <span class="flow-node-title">{{ node.label }}</span>
                  <span v-if="node._status==='running'" class="flow-node-badge running">运行中</span>
                  <span v-if="node._status==='done'" class="flow-node-badge done">✓</span>
                  <span v-if="node._status==='error'" class="flow-node-badge error">!</span>
                </div>
                <div class="flow-node-body">{{ nodeSummary(node) }}</div>
                <!-- 输入端口 -->
                <div v-if="node.type!=='start'" class="flow-port in"
                  :class="{ 'conn-target': connTargetId===node.id }"
                  @mousedown.stop="onPortMouseDown($event,node,'in')"></div>
                <!-- 输出端口 -->
                <div v-if="node.type!=='end'" class="flow-port out"
                  :class="{ active: draggingConn && draggingConn.from===node.id }"
                  @mousedown.stop="onPortMouseDown($event,node,'out')"></div>
                <!-- 删除按钮 -->
                <button v-if="node.type!=='start'&&node.type!=='end'" class="flow-node-del" @click.stop="removeNode(node.id)">✕</button>
              </div>
            </div>
          </div>
          <!-- 配置面板 -->
          <div class="flow-config" style="position: relative;">
            <!-- 变量选择器弹窗 -->
            <div v-if="varPickerOpen" class="var-picker-popup" @click.stop>
              <div class="var-picker-header">
                <span>选择变量</span>
                <button class="var-picker-close" @click="varPickerOpen = false">✕</button>
              </div>
              <div class="var-picker-list">
                <div v-for="v in availableVarsForSelected" :key="v.value"
                     class="var-picker-item" @click="insertVariable(v.value)">
                  <span class="var-hint-type" :class="v.type">{{ v.type }}</span>
                  <span class="var-picker-label">{{ v.label }}</span>
                </div>
                <div v-if="!availableVarsForSelected.length" class="var-picker-empty">
                  暂无可用变量，请先添加上游节点
                </div>
              </div>
            </div>
            <!-- Tab栏 -->
            <div class="config-tabs">
              <button class="config-tab" :class="{active: configTab==='node'}" @click="configTab='node'">⚙ 节点</button>
              <button class="config-tab" :class="{active: configTab==='vars'}" @click="configTab='vars'">📊 变量</button>
              <button class="config-tab" :class="{active: configTab==='trace'}" @click="configTab='trace'">📡 追踪</button>
            </div>

            <!-- ===== 节点配置Tab ===== -->
            <div v-show="configTab==='node'">
              <template v-if="selectedNodeData">
                <div class="config-header">
                  <span class="config-icon" :style="{background:nodeColor(selectedNodeData.type)}">{{ selectedNodeData.icon }}</span>
                  <span class="config-title">{{ selectedNodeData.label }}</span>
                  <span v-if="debugState.breakpoints.includes(selectedNodeData.id)" class="bp-badge">🔴 断点</span>
                </div>
                <div class="config-body">
                  <div class="config-field">
                    <label>节点名称</label>
                    <input v-model="selectedNodeData.label" type="text" class="config-input">
                  </div>
                  <!-- LLM 配置 -->
                  <template v-if="selectedNodeData.type==='llm'">
                    <div class="config-field">
                      <label>模型</label>
                      <select v-model="selectedNodeData.model" class="config-input">
                        <option value="deepseek-chat">DeepSeek Chat</option>
                        <option value="deepseek-coder">DeepSeek Coder</option>
                        <option value="gpt-4o">GPT-4o</option>
                        <option value="gpt-4o-mini">GPT-4o Mini</option>
                        <option value="claude-3.5-sonnet">Claude 3.5 Sonnet</option>
                      </select>
                    </div>
                    <div class="config-field">
                      <label>温度 ({{ selectedNodeData.temperature }})</label>
                      <input v-model.number="selectedNodeData.temperature" type="range" min="0" max="2" step="0.1" class="config-range">
                    </div>
                    <div class="config-field">
                    <label>系统提示词 <button class="var-btn" @click="openVarPicker($event, 'systemPrompt')" title="插入变量">{ }</button></label>
                    <textarea v-model="selectedNodeData.systemPrompt" ref="systemPromptEl" :placeholder="'你是一个专业的助手… 可用 {{#start-1.input#}} 引用变量'" class="config-textarea"></textarea>
                  </div>
                  <div class="config-field">
                    <label>用户提示词 <button class="var-btn" @click="openVarPicker($event, 'userPrompt')" title="插入变量">{ }</button></label>
                    <textarea v-model="selectedNodeData.userPrompt" ref="userPromptEl" :placeholder="'请根据以下内容回答：{{#start-1.input#}}'" class="config-textarea"></textarea>
                  </div>
                  </template>
                  <!-- HTTP 配置 -->
                  <template v-if="selectedNodeData.type==='http'">
                    <div class="config-field">
                      <label>请求方法</label>
                      <select v-model="selectedNodeData.method" class="config-input">
                        <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
                      </select>
                    </div>
                    <div class="config-field">
                      <label>URL <button class="var-btn" @click="openVarPicker($event, 'url')" title="插入变量">{ }</button></label>
                      <input v-model="selectedNodeData.url" type="text" :placeholder="'https://api.example.com/{{#start-1.input#}}'" class="config-input">
                    </div>
                    <div class="config-field">
                      <label>请求头 (JSON)</label>
                      <textarea v-model="selectedNodeData.headers" placeholder='{"Content-Type":"application/json"}' class="config-textarea"></textarea>
                    </div>
                    <div class="config-field">
                      <label>请求体</label>
                      <textarea v-model="selectedNodeData.body" placeholder='{"key":"value"}' class="config-textarea"></textarea>
                    </div>
                  </template>
                  <!-- 条件分支 -->
                  <template v-if="selectedNodeData.type==='condition'">
                    <div class="config-field">
                      <label>条件表达式</label>
                      <input v-model="selectedNodeData.condition" type="text" placeholder="output.includes('是')" class="config-input">
                    </div>
                    <div class="config-hint">真 → 上方分支，假 → 下方分支</div>
                  </template>
                  <!-- 代码执行 -->
                  <template v-if="selectedNodeData.type==='code'">
                    <div class="config-field">
                      <label>语言</label>
                      <select v-model="selectedNodeData.lang" class="config-input">
                        <option value="python">Python</option>
                        <option value="javascript">JavaScript</option>
                      </select>
                    </div>
                    <div class="config-field">
                      <label>代码</label>
                      <textarea v-model="selectedNodeData.code" :placeholder="'# 可通过 {{#start-1.input#}} 引用上游变量\nresult = input.upper()\nreturn result'" class="config-code"></textarea>
                    </div>
                  </template>
                  <!-- 模板 -->
                  <template v-if="selectedNodeData.type==='template'">
                    <div class="config-field">
                      <label>模板内容 (Jinja2) <button class="var-btn" @click="openVarPicker($event, 'template')" title="插入变量">{ }</button></label>
                      <textarea v-model="selectedNodeData.template" :placeholder="'你好 {{#start-1.input#}}，今天是 {{date}}'" class="config-textarea"></textarea>
                    </div>
                  </template>
                  <!-- 变量赋值 -->
                  <template v-if="selectedNodeData.type==='variable'">
                    <div class="config-field">
                      <label>变量名</label>
                      <input v-model="selectedNodeData.varName" type="text" placeholder="result" class="config-input">
                    </div>
                    <div class="config-field">
                      <label>变量值 <button class="var-btn" @click="openVarPicker($event, 'varValue')" title="插入变量">{ }</button></label>
                      <input v-model="selectedNodeData.varValue" type="text" :placeholder="'{{#start-1.input#}}'" class="config-input">
                    </div>
                  </template>
                  <!-- 知识检索 -->
                  <template v-if="selectedNodeData.type==='knowledge'">
                    <div class="config-field">
                      <label>检索关键词 <button class="var-btn" @click="openVarPicker($event, 'query')" title="插入变量">{ }</button></label>
                      <input v-model="selectedNodeData.query" type="text" :placeholder="'{{#start-1.input#}}'" class="config-input">
                    </div>
                    <div class="config-field">
                      <label>返回数量</label>
                      <input v-model.number="selectedNodeData.topK" type="number" min="1" max="10" class="config-input">
                    </div>
                  </template>
                  <!-- 工具 -->
                  <template v-if="selectedNodeData.type==='tool'">
                    <div class="config-field">
                      <label>工具</label>
                      <select v-model="selectedNodeData.toolName" class="config-input">
                        <option value="web_search">网页搜索</option>
                        <option value="image_gen">图片生成</option>
                        <option value="code_run">代码执行</option>
                        <option value="file_read">文件读取</option>
                      </select>
                    </div>
                  </template>
                  <!-- 开始节点 -->
                  <template v-if="selectedNodeData.type==='start'">
                    <div class="config-field">
                      <label>默认输入值</label>
                      <input v-model="topic" type="text" placeholder="用户输入内容，如城市名" class="config-input">
                    </div>
                    <div class="config-hint" v-pre>开始节点是工作流的入口，运行时此值作为变量 {{#start-1.input#}} 传递给下游节点。</div>
                  </template>
                  <!-- 结束节点 -->
                  <template v-if="selectedNodeData.type==='end'">
                    <div class="config-field">
                      <label>输出变量 <button class="var-btn" @click="openVarPicker($event, 'outputVar')" title="插入变量">{ }</button></label>
                      <input v-model="selectedNodeData.outputVar" type="text" :placeholder="'{{#llm-1.text#}}'" class="config-input">
                    </div>
                  </template>
                  <!-- 可用变量提示 -->
                  <div v-if="availableVarsForSelected.length" class="var-hint-section">
                    <div class="var-hint-title">📋 可用变量（点击复制）</div>
                    <div v-for="v in availableVarsForSelected" :key="v.value"
                         class="var-hint-item" @click="copyVarRef(v.value)">
                      <span class="var-hint-type" :class="v.type">{{ v.type }}</span>
                      <span class="var-hint-label">{{ v.label }}</span>
                      <span class="var-hint-ref" v-text="'{{#' + v.value + '#}}'"></span>
                    </div>
                  </div>
                </div>
              </template>
              <template v-else-if="selectedEdge>=0">
                <div class="config-header"><span class="config-icon">🔗</span><span class="config-title">连线配置</span></div>
                <div class="config-body">
                  <button class="btn-mini danger" @click="removeEdge(selectedEdge)">删除连线</button>
                </div>
              </template>
              <template v-else>
                <div class="config-empty">
                  <div style="font-size:28px;opacity:.3;margin-bottom:8px">🧩</div>
                  <div>点击节点或连线进行配置</div>
                  <div style="font-size:11px;margin-top:6px;opacity:.6">从左侧面板添加节点<br>拖拽节点端口创建连线<br>滚轮缩放 · 拖拽空白处平移画布</div>
                </div>
              </template>
            </div>

            <!-- ===== 变量检查器Tab ===== -->
            <div v-show="configTab==='vars'" class="config-body">
              <div v-if="!Object.keys(variablePool.nodes).length && !variablePool.sys.workflow_run_id" class="config-empty">
                <div style="font-size:28px;opacity:.3;margin-bottom:8px">📊</div>
                <div>运行工作流后查看变量</div>
                <div style="font-size:11px;margin-top:6px;opacity:.6">变量检查器显示所有变量的当前值<br>可在逐步执行时编辑变量测试不同场景</div>
              </div>
              <template v-else>
                <!-- 系统变量 -->
                <div class="var-inspector-group">
                  <div class="var-inspector-title">🔧 系统变量</div>
                  <div v-for="(v, k) in variablePool.sys" :key="'sys'+k" class="var-inspector-item">
                    <span class="var-inspector-name">sys.{{ k }}</span>
                    <span class="var-inspector-val">{{ v }}</span>
                  </div>
                </div>
                <!-- 输入变量 -->
                <div v-if="Object.keys(variablePool.input).length" class="var-inspector-group">
                  <div class="var-inspector-title">📥 输入变量</div>
                  <div v-for="(v, k) in variablePool.input" :key="'in'+k" class="var-inspector-item">
                    <span class="var-inspector-name">input.{{ k }}</span>
                    <span class="var-inspector-val">{{ v }}</span>
                  </div>
                </div>
                <!-- 节点输出变量 -->
                <div class="var-inspector-group">
                  <div class="var-inspector-title">📤 节点输出</div>
                  <div v-for="(output, nodeId) in variablePool.nodes" :key="nodeId" class="var-inspector-node">
                    <div class="var-inspector-node-header">
                      <span class="var-inspector-node-icon">{{ nodes.find(n=>n.id===nodeId)?.icon || '🔧' }}</span>
                      <span class="var-inspector-node-name">{{ nodes.find(n=>n.id===nodeId)?.label || nodeId }}</span>
                    </div>
                    <div v-for="(v, k) in output" :key="nodeId+k" class="var-inspector-item">
                      <span class="var-inspector-name">{{ k }}</span>
                      <input v-if="typeof v === 'string' || typeof v === 'number'"
                             v-model="variablePool.nodes[nodeId][k]" class="var-inspector-edit" />
                      <pre v-else class="var-inspector-obj">{{ JSON.stringify(v, null, 2) }}</pre>
                    </div>
                  </div>
                </div>
              </template>
            </div>

            <!-- ===== 执行追踪Tab ===== -->
            <div v-show="configTab==='trace'" class="config-body">
              <div v-if="!debugState.execHistory.length" class="config-empty">
                <div style="font-size:28px;opacity:.3;margin-bottom:8px">📡</div>
                <div>暂无执行记录</div>
                <div style="font-size:11px;margin-top:6px;opacity:.6">运行工作流后查看执行追踪<br>每个节点的输入、输出、耗时将显示在此</div>
              </div>
              <div v-else>
                <div class="trace-summary">
                  <span>共 {{ debugState.execHistory.length }} 条记录</span>
                  <button class="btn-mini" @click="debugState.execHistory = []; tracePage = 1">清空</button>
                </div>
                <div v-for="(record, i) in pagedTrace" :key="(tracePage - 1) * tracePageSize + i"
                     class="trace-item" :class="{ error: record.error }">
                  <div class="trace-header" @click="record._expanded = !record._expanded">
                    <span class="trace-icon" :class="record.error ? 'err' : 'ok'">{{ record.error ? '✕' : '✓' }}</span>
                    <span class="trace-label">{{ record.icon }} {{ record.nodeLabel }}</span>
                    <span class="trace-duration">{{ record.duration.toFixed(0) }}ms</span>
                    <span class="trace-expand">{{ record._expanded ? '▼' : '▶' }}</span>
                  </div>
                  <div v-if="record._expanded" class="trace-detail">
                    <div class="trace-section">
                      <div class="trace-section-title">输入</div>
                      <pre class="trace-code">{{ formatTraceData(record.input) }}</pre>
                    </div>
                    <div class="trace-section">
                      <div class="trace-section-title">输出</div>
                      <pre class="trace-code">{{ formatTraceData(record.output) }}</pre>
                    </div>
                    <div v-if="record.error" class="trace-section">
                      <div class="trace-section-title error">错误</div>
                      <pre class="trace-code error">{{ record.error }}</pre>
                    </div>
                  </div>
                </div>
                <!-- 分页 -->
                <div v-if="debugState.execHistory.length > tracePageSize" class="skill-pagination">
                  <button class="page-btn" :disabled="tracePage === 1" @click="tracePage--">‹</button>
                  <button v-for="p in traceTotalPages" :key="p" class="page-num" :class="{ active: p === tracePage }" @click="tracePage = p">{{ p }}</button>
                  <button class="page-btn" :disabled="tracePage === traceTotalPages" @click="tracePage++">›</button>
                  <span class="page-info">{{ tracePage }}/{{ traceTotalPages }} 页 · {{ debugState.execHistory.length }} 条</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="flowResult" class="flow-run-result">
          <span style="font-weight:700">▶ 运行结果：</span>
          <span>{{ flowResult }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import wsManager from '../utils/wsManager.js'

const section = ref('input')
const topic = ref('')
const running = ref(false)
const error = ref('')
const result = ref('')

const wfRunning = ref(false)
const wfTaskId = ref(null)
const wfNodeRuns = ref([])
const wfUnsub = ref(null)
const wfError = ref('')
const flowName = ref('')

// === 画布状态 ===
const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
const nodes = ref([])
const connections = ref([])
const selectedNode = ref(null)
const selectedEdge = ref(-1)
const flowResult = ref('')
const savedFlows = ref([])
const taskSearch = ref('')
const taskFilter = ref('all') // all | builtin | user
const taskPage = ref(1)
const taskPageSize = 6
const tracePage = ref(1)
const tracePageSize = 4
const resultList = ref([])
const resultSearch = ref('')
const resultPage = ref(1)
const resultPageSize = 6
const selectedResultId = ref(null)

// 任务列表过滤+分页
const filteredFlows = computed(() => {
  let list = savedFlows.value
  // 筛选
  if (taskFilter.value === 'builtin') list = list.filter(f => f.builtin)
  else if (taskFilter.value === 'user') list = list.filter(f => !f.builtin)
  // 搜索
  const q = taskSearch.value.trim().toLowerCase()
  if (q) list = list.filter(f => f.name.toLowerCase().includes(q))
  return list
})

const taskTotalPages = computed(() => Math.max(1, Math.ceil(filteredFlows.value.length / taskPageSize)))

const pagedFlows = computed(() => {
  const start = (taskPage.value - 1) * taskPageSize
  return filteredFlows.value.slice(start, start + taskPageSize)
})

function onTaskSearch() { taskPage.value = 1 }

// 运行结果列表过滤+分页
const filteredResults = computed(() => {
  const q = resultSearch.value.trim().toLowerCase()
  let list = resultList.value
  if (q) {
    list = list.filter(r =>
      r.flowName.toLowerCase().includes(q) ||
      (r.result || '').toLowerCase().includes(q)
    )
  }
  return [...list].sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))
})
const resultTotalPages = computed(() => Math.max(1, Math.ceil(filteredResults.value.length / resultPageSize)))
const pagedResults = computed(() => {
  const start = (resultPage.value - 1) * resultPageSize
  return filteredResults.value.slice(start, start + resultPageSize)
})
const selectedResult = computed(() => resultList.value.find(r => r.id === selectedResultId.value) || null)
function onResultSearch() { resultPage.value = 1 }
function deleteResult(id) {
  resultList.value = resultList.value.filter(r => r.id !== id)
  if (selectedResultId.value === id) selectedResultId.value = null
  persistResultList()
}
function clearAllResults() {
  resultList.value = []
  selectedResultId.value = null
  persistResultList()
}
function persistResultList() {
  try {
    localStorage.setItem('flow_result_list', JSON.stringify(resultList.value))
  } catch {}
}
function loadResultList() {
  try {
    const raw = localStorage.getItem('flow_result_list')
    if (raw) resultList.value = JSON.parse(raw)
  } catch {}
}

// 执行追踪分页
const traceTotalPages = computed(() => Math.max(1, Math.ceil(debugState.value.execHistory.length / tracePageSize)))

const nodeStatusMap = computed(() => {
  const map = {}
  for (const r of wfNodeRuns.value) {
    map[r.id] = r.status
  }
  return map
})

watch(wfNodeRuns, (runs) => {
  for (const n of nodes.value) {
    const run = runs.find(r => r.id === n.id)
    if (!run) continue
    if (run.status === 'running') n._status = 'running'
    else if (run.status === 'succeeded') n._status = 'done'
    else if (run.status === 'failed') n._status = 'error'
  }
}, { deep: true })
const pagedTrace = computed(() => {
  const start = (tracePage.value - 1) * tracePageSize
  return debugState.value.execHistory.slice(start, start + tracePageSize)
})

// 内置模板定义（持久化在代码中，不依赖 localStorage）
const builtinFlows = [
  {
    name: '天气查询',
    icon: '🌤',
    desc: '5 个节点 · 5 条连线',
    builtin: true,
    loader: 'loadWeatherFlow'
  }
]

// === 变量池 ===
const variablePool = ref({
  sys: { user_id: 'user_demo', workflow_id: '', workflow_run_id: '', timestamp: 0 },
  env: {},
  input: {},
  nodes: {}  // { 'llm-1': { text: '...', usage: {...} }, ... }
})

// === 调试状态 ===
const configTab = ref('node')  // 'node' | 'vars' | 'trace'
const debugState = ref({
  mode: 'full',           // 'full' | 'step' | 'single'
  stepQueue: [],          // 逐步执行的待执行节点队列
  isStepping: false,      // 是否正在逐步执行
  execHistory: [],        // 执行历史记录
  breakpoints: [],        // 断点节点ID列表
  paused: false           // 是否暂停在断点
})

// === 变量选择器弹窗 ===
const varPickerOpen = ref(false)
const varPickerTarget = ref(null)  // 目标字段名
const varPickerEl = ref(null)      // 目标DOM元素

// === 面板拖拽到画布 ===
const dragFromPalette = ref(null)  // 正在拖拽的节点类型

// === 拖拽状态（全部响应式） ===
const draggingNode = ref(null)
const draggingNodeId = ref(null)
let draggingOffset = { x: 0, y: 0 }
const draggingConn = ref(null)
const dragPath = ref('')
const connTargetId = ref(null)
const isPanningActive = ref(false)
let panStart = { x: 0, y: 0, px: 0, py: 0 }

// === 节点类型定义 ===
const nodeTypes = [
  { type: 'start', label: '开始', icon: '▶', color: 'rgba(16,185,129,.18)', w: 180, h: 68 },
  { type: 'end', label: '结束', icon: '■', color: 'rgba(239,68,68,.18)', w: 180, h: 68 },
  { type: 'llm', label: 'LLM', icon: '🤖', color: 'rgba(139,92,246,.18)', w: 200, h: 68 },
  { type: 'http', label: 'HTTP 请求', icon: '🔗', color: 'rgba(59,130,246,.18)', w: 200, h: 68 },
  { type: 'code', label: '代码执行', icon: '⚡', color: 'rgba(20,184,166,.18)', w: 200, h: 68 },
  { type: 'template', label: '模板', icon: '📝', color: 'rgba(236,72,153,.18)', w: 200, h: 68 },
  { type: 'condition', label: '条件分支', icon: '🔀', color: 'rgba(245,158,11,.18)', w: 200, h: 68 },
  { type: 'variable', label: '变量赋值', icon: '📦', color: 'rgba(100,116,139,.18)', w: 200, h: 68 },
  { type: 'knowledge', label: '知识检索', icon: '📚', color: 'rgba(34,197,94,.18)', w: 200, h: 68 },
  { type: 'tool', label: '工具', icon: '🛠️', color: 'rgba(168,85,247,.18)', w: 200, h: 68 },
]

const nodeTypeMap = computed(() => {
  const m = {}
  nodeTypes.forEach(t => { m[t.type] = t })
  return m
})

const flowViewBox = computed(() => {
  if (!nodes.value.length) return { x: 0, y: 0, w: 3000, h: 2000 }
  let maxX = 0, maxY = 0
  nodes.value.forEach(n => {
    const w = nodeTypeMap.value[n.type]?.w || 200
    const h = nodeTypeMap.value[n.type]?.h || 68
    maxX = Math.max(maxX, n.x + w + 100)
    maxY = Math.max(maxY, n.y + h + 100)
  })
  connections.value.forEach(c => {
    const fromNode = nodes.value.find(n => n.id === c.from)
    const toNode = nodes.value.find(n => n.id === c.to)
    if (fromNode) {
      const w = nodeTypeMap.value[fromNode.type]?.w || 200
      const h = nodeTypeMap.value[fromNode.type]?.h || 68
      maxX = Math.max(maxX, fromNode.x + w + 100)
      maxY = Math.max(maxY, fromNode.y + h + 100)
    }
    if (toNode) {
      const w = nodeTypeMap.value[toNode.type]?.w || 200
      const h = nodeTypeMap.value[toNode.type]?.h || 68
      maxX = Math.max(maxX, toNode.x + w + 100)
      maxY = Math.max(maxY, toNode.y + h + 100)
    }
  })
  return { x: 0, y: 0, w: Math.max(Math.ceil(maxX), 2000), h: Math.max(Math.ceil(maxY), 1500) }
})

const flowSvgStyle = computed(() => {
  const vb = flowViewBox.value
  return {
    width: vb.w + 'px',
    height: vb.h + 'px'
  }
})

// === 节点输出Schema：定义每种节点产生的输出变量 ===
const nodeOutputSchema = {
  start: [{ field: 'input', type: 'string', label: '用户输入' }],
  end: [{ field: 'output', type: 'string', label: '最终输出' }],
  llm: [
    { field: 'text', type: 'string', label: '生成文本' },
    { field: 'usage', type: 'object', label: 'Token用量' }
  ],
  http: [
    { field: 'body', type: 'string', label: '响应体' },
    { field: 'status_code', type: 'number', label: '状态码' },
    { field: 'headers', type: 'object', label: '响应头' }
  ],
  code: [{ field: 'result', type: 'object', label: '返回值' }],
  template: [{ field: 'text', type: 'string', label: '渲染结果' }],
  condition: [{ field: 'branch', type: 'string', label: '选中分支' }],
  variable: [{ field: 'value', type: 'string', label: '变量值' }],
  knowledge: [{ field: 'result', type: 'array[object]', label: '检索结果' }],
  tool: [{ field: 'output', type: 'string', label: '工具输出' }]
}

const selectedNodeData = computed(() => nodes.value.find(n => n.id === selectedNode.value) || null)

const templates = [
  { icon: '📊', title: '行业调研报告', desc: '针对特定行业进行深度调研，生成结构化分析报告', topic: 'AI智能体行业调研报告' },
  { icon: '🔬', title: '技术深度分析', desc: '分析技术原理、应用场景与发展趋势', topic: '大语言模型技术分析' },
  { icon: '📝', title: '营销文案', desc: '生成品牌营销内容与推广文案', topic: '智能体产品营销文案' },
  { icon: '🚀', title: '商业计划书', desc: '撰写完整的商业计划与可行性分析', topic: 'AI创业项目商业计划书' },
  { icon: '🌤', title: '天气查询工作流', desc: '可视化编排示例：HTTP获取天气数据 → LLM生成天气播报', topic: '__weather_flow__' },
]

// === 模板点击处理 ===
function onTemplateClick(t) {
  if (t.topic === '__weather_flow__') {
    loadWeatherFlow()
  } else {
    topic.value = t.topic
  }
}

// === 天气查询工作流案例 ===
function loadWeatherFlow() {
  clearFlowSilent()
  flowName.value = '天气查询'
  topic.value = '北京'

  // 开始节点 - 用户输入城市名
  nodes.value.push({
    id: 'start-1', type: 'start', label: '开始', icon: '▶',
    x: 80, y: 120, _status: '', _output: '',
    model: 'deepseek-chat', temperature: 0.7, systemPrompt: '', userPrompt: '',
    method: 'GET', url: '', headers: '', body: '',
    condition: '', lang: 'python', code: '',
    template: '', varName: '', varValue: '',
    query: '', topK: 3, toolName: 'web_search', outputVar: ''
  })

  // HTTP请求节点 - 查询城市坐标
  nodes.value.push({
    id: 'http-2', type: 'http', label: '查询城市坐标', icon: '🔗',
    x: 320, y: 150, _status: '', _output: '',
    model: 'deepseek-chat', temperature: 0.7, systemPrompt: '', userPrompt: '',
    method: 'GET',
    url: 'https://geocoding-api.open-meteo.com/v1/search?name={{#start-1.input#}}&count=1&language=zh&format=json',
    headers: '{"Accept":"application/json"}', body: '',
    condition: '', lang: 'python', code: '',
    template: '', varName: '', varValue: '',
    query: '', topK: 3, toolName: 'web_search', outputVar: ''
  })

  // HTTP请求节点 - 查询天气
  nodes.value.push({
    id: 'http-3', type: 'http', label: '获取天气数据', icon: '🌡',
    x: 560, y: 150, _status: '', _output: '',
    model: 'deepseek-chat', temperature: 0.7, systemPrompt: '', userPrompt: '',
    method: 'GET',
    url: 'https://api.open-meteo.com/v1/forecast?latitude={{#http-2.body.results.0.latitude#}}&longitude={{#http-2.body.results.0.longitude#}}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&timezone=Asia/Shanghai',
    headers: '{"Accept":"application/json"}', body: '',
    condition: '', lang: 'python', code: '',
    template: '', varName: '', varValue: '',
    query: '', topK: 3, toolName: 'web_search', outputVar: ''
  })

  // LLM节点 - 生成天气播报
  nodes.value.push({
    id: 'llm-4', type: 'llm', label: '天气播报生成', icon: '🤖',
    x: 800, y: 150, _status: '', _output: '',
    model: 'deepseek-chat', temperature: 0.5,
    systemPrompt: '你是一个专业的天气预报员。请根据提供的天气数据，用简洁友好的语言生成天气播报。包括温度、湿度、天气状况和风速。最后给出穿衣建议。',
    userPrompt: '城市坐标查询结果: {{#http-2.body#}}\n\n天气数据: {{#http-3.body#}}\n\n请生成天气播报：',
    method: 'GET', url: '', headers: '', body: '',
    condition: '', lang: 'python', code: '',
    template: '', varName: '', varValue: '',
    query: '', topK: 3, toolName: 'web_search', outputVar: ''
  })

  // 结束节点 - 输出天气播报
  nodes.value.push({
    id: 'end-5', type: 'end', label: '结束', icon: '■',
    x: 1040, y: 150, _status: '', _output: '',
    model: 'deepseek-chat', temperature: 0.7, systemPrompt: '', userPrompt: '',
    method: 'GET', url: '', headers: '', body: '',
    condition: '', lang: 'python', code: '',
    template: '', varName: '', varValue: '',
    query: '', topK: 3, toolName: 'web_search', outputVar: '{{#llm-4.text#}}'
  })

  // 连线
  connections.value.push(
    { from: 'start-1', to: 'http-2' },
    { from: 'http-2', to: 'http-3' },
    { from: 'http-2', to: 'llm-4' },
    { from: 'http-3', to: 'llm-4' },
    { from: 'llm-4', to: 'end-5' }
  )

  nodeCounter = 5
  selectedNode.value = null
  selectedEdge.value = -1

  // 切换到可视化编排页面
  section.value = 'flow'
  flowResult.value = '🌤 天气查询工作流已加载！\n流程: 开始 → 查询城市坐标 → 获取天气数据 → LLM生成播报 → 结束\n\n点击「▶ 运行」执行工作流，或点击节点查看配置。\n提示: 点击「开始」节点可修改查询城市。'

  // 自动保存到 localStorage
  saveFlow()
}

// === 变量引用解析 ===
// 解析 {{#nodeId.field#}} 或 {{nodeId.field}} 格式的变量引用
// 支持: sys.xxx, env.xxx, nodeId.field (从nodes池查找)
function resolveVariables(template, pool) {
  if (!template || typeof template !== 'string') return template
  return template.replace(/\{\{#?([\w.-]+)#?\}\}/g, (match, path) => {
    const trimmed = path.trim()
    let val
    if (trimmed.startsWith('sys.')) {
      // 系统变量: sys.user_id → pool.sys.user_id
      const key = trimmed.slice(4)
      val = pool.sys?.[key]
    } else if (trimmed.startsWith('env.')) {
      // 环境变量: env.API_KEY → pool.env.API_KEY
      const key = trimmed.slice(4)
      val = pool.env?.[key]
    } else {
      // 节点输出变量: http-2.body.results.0.latitude → pool.nodes['http-2']['body']['results'][0]['latitude']
      const dotIdx = trimmed.indexOf('.')
      if (dotIdx > 0) {
        const nodeId = trimmed.slice(0, dotIdx)
        const fieldPath = trimmed.slice(dotIdx + 1)
        val = pool.nodes?.[nodeId]
        // 逐层解析嵌套路径 (支持 body.results.0.latitude)
        if (val !== undefined) {
          for (const part of fieldPath.split('.')) {
            if (val === undefined || val === null) break
            val = val[part]
          }
        }
        // 如果是对象，返回JSON字符串以便在URL中使用
        if (val !== undefined && val !== null && typeof val === 'object') {
          val = JSON.stringify(val)
        }
      }
    }
    if (val === undefined) return match
    if (val === null) return ''
    if (typeof val === 'object') return JSON.stringify(val)
    return String(val)
  })
}

// 获取节点的上游节点ID列表（递归）
function getUpstreamNodeIds(nodeId) {
  const result = new Set()
  const queue = [nodeId]
  while (queue.length) {
    const id = queue.shift()
    connections.value.filter(c => c.to === id).forEach(c => {
      if (!result.has(c.from)) { result.add(c.from); queue.push(c.from) }
    })
  }
  return Array.from(result)
}

// 获取当前节点可引用的变量列表
function getAvailableVariables(nodeId) {
  const vars = []
  // 系统变量
  Object.entries(variablePool.value.sys).forEach(([k, v]) => {
    if (v) vars.push({ label: `sys.${k}`, value: `sys.${k}`, type: typeof v, group: '系统变量' })
  })
  // 上游节点输出
  const upstreamIds = getUpstreamNodeIds(nodeId)
  upstreamIds.forEach(uid => {
    const node = nodes.value.find(n => n.id === uid)
    if (!node) return
    const schema = nodeOutputSchema[node.type] || []
    schema.forEach(s => {
      vars.push({
        label: `${node.label}.${s.field}`,
        value: `${uid}.${s.field}`,
        type: s.type,
        group: `${node.icon} ${node.label}`
      })
    })
  })
  return vars
}

// 计算当前选中节点可用变量（用于模板显示）
const availableVarsForSelected = computed(() => {
  if (!selectedNode.value) return []
  return getAvailableVariables(selectedNode.value)
})

// 解析节点配置中的变量引用
function resolveNodeConfig(node, pool) {
  const resolved = { ...node }
  const fields = ['systemPrompt', 'userPrompt', 'url', 'headers', 'body',
                  'condition', 'code', 'template', 'varValue', 'query', 'outputVar']
  fields.forEach(f => {
    if (resolved[f]) resolved[f] = resolveVariables(resolved[f], pool)
  })
  return resolved
}

// 格式化节点输出为显示文本
function formatNodeOutput(output) {
  if (!output) return ''
  const parts = []
  for (const [k, v] of Object.entries(output)) {
    if (typeof v === 'object') parts.push(`${k}: ${JSON.stringify(v).substring(0, 60)}`)
    else parts.push(`${k}: ${v}`)
  }
  return parts.join(' | ')
}

// 复制变量引用到剪贴板
function copyVarRef(varPath) {
  const ref = `{{#${varPath}#}}`
  navigator.clipboard.writeText(ref)
  const btn = event?.target?.closest('.var-hint-item')
  if (btn) {
    btn.classList.add('copied')
    setTimeout(() => btn.classList.remove('copied'), 600)
  }
}

// === 变量选择器弹窗 ===
function openVarPicker(e, fieldName) {
  e.stopPropagation()
  varPickerTarget.value = fieldName
  varPickerOpen.value = true
}

function insertVariable(varPath) {
  const ref = `{{#${varPath}#}}`
  const field = varPickerTarget.value
  if (field && selectedNodeData.value) {
    selectedNodeData.value[field] = (selectedNodeData.value[field] || '') + ref
  }
  varPickerOpen.value = false
}

// === 从面板拖拽到画布 ===
function onPaletteDragStart(e, pt) {
  dragFromPalette.value = pt
  e.dataTransfer.effectAllowed = 'copy'
  e.dataTransfer.setData('text/plain', pt.type)
}

function onCanvasDragOver(e) {
  e.dataTransfer.dropEffect = 'copy'
}

function onCanvasDragLeave() {
  // 不立即清空，因为dragleave可能在子元素间触发
}

function onCanvasDrop(e) {
  if (!dragFromPalette.value) return
  const pt = dragFromPalette.value
  dragFromPalette.value = null
  const canvasRect = e.currentTarget.getBoundingClientRect()
  const mx = (e.clientX - canvasRect.left - panX.value) / zoom.value
  const my = (e.clientY - canvasRect.top - panY.value) / zoom.value
  // 检查是否已存在同类型节点（start/end唯一）
  if (pt.type === 'start' && nodes.value.some(n => n.type === 'start')) {
    flowResult.value = '已存在开始节点'
    return
  }
  if (pt.type === 'end' && nodes.value.some(n => n.type === 'end')) {
    flowResult.value = '已存在结束节点'
    return
  }
  const id = pt.type + '-' + (++nodeCounter)
  const node = {
    id, type: pt.type, label: pt.label, icon: pt.icon,
    x: mx - (pt.w || 180) / 2, y: my - (pt.h || 70) / 2,
    _status: '', _output: '',
    model: 'deepseek-chat', temperature: 0.7, systemPrompt: '', userPrompt: '',
    method: 'GET', url: '', headers: '', body: '',
    condition: '', lang: 'python', code: '',
    template: '', varName: '', varValue: '',
    query: '', topK: 3, toolName: 'web_search', outputVar: ''
  }
  nodes.value.push(node)
  selectedNode.value = id
  selectedEdge.value = -1
}

// === 工作流导入导出 ===
const importInput = ref(null)

function exportFlow() {
  const data = {
    version: '1.0',
    name: flowName.value || '未命名工作流',
    exportedAt: new Date().toISOString(),
    nodes: nodes.value.map(n => {
      const { _status, _output, ...config } = n
      return config
    }),
    connections: connections.value.map(c => ({ ...c }))
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = (flowName.value || 'workflow') + '.json'
  a.click()
  URL.revokeObjectURL(url)
  flowResult.value = `已导出 ${nodes.value.length} 个节点, ${connections.value.length} 条连线`
}

function importFlow() {
  if (importInput.value) importInput.value.click()
}

function onImportFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => {
    try {
      const data = JSON.parse(ev.target.result)
      if (!data.nodes || !Array.isArray(data.nodes)) throw new Error('无效的工作流文件')
      clearFlow()
      flowName.value = data.name || '导入的工作流'
      // 恢复节点
      data.nodes.forEach(n => {
        nodes.value.push({ ...n, _status: '', _output: '' })
        const num = parseInt(n.id.split('-').pop())
        if (num > nodeCounter) nodeCounter = num
      })
      // 恢复连线
      if (data.connections && Array.isArray(data.connections)) {
        data.connections.forEach(c => connections.value.push({ ...c }))
      }
      flowResult.value = `已导入 ${data.nodes.length} 个节点, ${data.connections?.length || 0} 条连线`
    } catch (err) {
      flowResult.value = `导入失败: ${err.message}`
    }
  }
  reader.readAsText(file)
  e.target.value = ''
}

// === 节点操作 ===
let nodeCounter = 0
function addNode(pt) {
  if (pt.type === 'start' && nodes.value.some(n => n.type === 'start')) { alert('已存在开始节点'); return }
  if (pt.type === 'end' && nodes.value.some(n => n.type === 'end')) { alert('已存在结束节点'); return }
  const id = pt.type + '-' + (++nodeCounter)
  const count = nodes.value.length
  const node = {
    id, type: pt.type, label: pt.label, icon: pt.icon,
    x: 80 + count * 260 - panX.value / zoom.value,
    y: 120 - panY.value / zoom.value,
    _status: '', _output: '',
    model: 'deepseek-chat', temperature: 0.7, systemPrompt: '', userPrompt: '',
    method: 'GET', url: '', headers: '{"Content-Type":"application/json"}', body: '',
    condition: '', lang: 'python', code: '', template: '',
    varName: '', varValue: '', query: '', topK: 3,
    toolName: 'web_search', outputVar: '',
  }
  nodes.value.push(node)
  selectedNode.value = id
  selectedEdge.value = -1
}

function nodeColor(type) { return nodeTypeMap.value[type]?.color || 'rgba(100,116,139,.18)' }

function nodeSummary(node) {
  if (node.type === 'llm') return node.model || '未配置模型'
  if (node.type === 'http') return `${node.method || 'GET'} ${node.url || '未配置URL'}`
  if (node.type === 'code') return `${node.lang || 'python'} · ${node.code ? '已编写' : '未编写'}`
  if (node.type === 'template') return node.template ? '已配置模板' : '未配置模板'
  if (node.type === 'condition') return node.condition || '未配置条件'
  if (node.type === 'variable') return `${node.varName || '变量'} = ${node.varValue || '?'}`
  if (node.type === 'knowledge') return `topK=${node.topK || 3}`
  if (node.type === 'tool') return node.toolName || '未选择工具'
  if (node.type === 'start') return '工作流入口'
  if (node.type === 'end') return node.outputVar || '输出结果'
  return ''
}

function removeNode(id) {
  const idx = nodes.value.findIndex(n => n.id === id)
  if (idx < 0) return
  nodes.value.splice(idx, 1)
  connections.value = connections.value.filter(c => c.from !== id && c.to !== id)
  selectedNode.value = null
}

function selectNode(id) {
  selectedNode.value = id
  selectedEdge.value = -1
}

function selectEdge(i) {
  selectedEdge.value = i
  selectedNode.value = null
}

function removeEdge(i) {
  connections.value.splice(i, 1)
  selectedEdge.value = -1
}

// === 端口位置 ===
// 端口CSS: width=14px, right/left=-8px
// 端口中心相对于节点边缘的偏移 = -8 + 14/2 = -1 (即端口中心在节点边缘外1px)
const PORT_OFFSET = 1
function nodePortPos(nodeId, port) {
  const node = nodes.value.find(n => n.id === nodeId)
  if (!node) return { x: 0, y: 0 }
  const nt = nodeTypeMap.value[node.type]
  const w = nt?.w || 200
  const h = nt?.h || 68
  if (port === 'in') return { x: node.x - PORT_OFFSET, y: node.y + h / 2 }
  return { x: node.x + w + PORT_OFFSET, y: node.y + h / 2 }
}

// === 通过DOM元素获取端口位置（用于调试） ===
function getPortPosFromDOM(nodeId, port) {
  const nodeEl = document.querySelector(`.flow-node[data-id="${nodeId}"]`)
  if (!nodeEl) return null
  const portEl = nodeEl.querySelector(`.flow-port.${port}`)
  if (!portEl) return null
  const canvasEl = document.querySelector('.flow-canvas-box')
  if (!canvasEl) return null
  const canvasRect = canvasEl.getBoundingClientRect()
  const portRect = portEl.getBoundingClientRect()
  return {
    x: (portRect.left + portRect.width/2 - canvasRect.left - panX.value) / zoom.value,
    y: (portRect.top + portRect.height/2 - canvasRect.top - panY.value) / zoom.value
  }
}

function bezierPath(conn) {
  const from = nodePortPos(conn.from, 'out')
  const to = nodePortPos(conn.to, 'in')
  const dx = Math.abs(to.x - from.x) * 0.5
  return `M ${from.x} ${from.y} C ${from.x + dx} ${from.y}, ${to.x - dx} ${to.y}, ${to.x} ${to.y}`
}

// === 坐标转换 ===
function screenToCanvas(clientX, clientY) {
  const canvasEl = document.querySelector('.flow-canvas-box')
  if (!canvasEl) return { x: 0, y: 0 }
  const rect = canvasEl.getBoundingClientRect()
  return {
    x: (clientX - rect.left - panX.value) / zoom.value,
    y: (clientY - rect.top - panY.value) / zoom.value,
  }
}

// === 鼠标事件：节点拖拽 ===
function onNodeMouseDown(e, node) {
  draggingNode.value = node
  draggingNodeId.value = node.id
  const rect = e.currentTarget.getBoundingClientRect()
  draggingOffset = {
    x: (e.clientX - rect.left) / zoom.value,
    y: (e.clientY - rect.top) / zoom.value,
  }
}

// === 鼠标事件：端口连线 ===
function onPortMouseDown(e, node, portType) {
  if (portType === 'in') {
    // 如果已有连线连入此端口，可以反向拖拽
    const existingConn = connections.value.findIndex(c => c.to === node.id)
    if (existingConn >= 0) {
      const conn = connections.value[existingConn]
      connections.value.splice(existingConn, 1)
      const pos = nodePortPos(conn.from, 'out')
      draggingConn.value = { from: conn.from, mouseX: pos.x, mouseY: pos.y }
      e.preventDefault()
    }
    return
  }
  e.preventDefault()
  const pos = nodePortPos(node.id, 'out')
  draggingConn.value = { from: node.id, mouseX: pos.x, mouseY: pos.y }
}

// === 鼠标事件：画布平移 ===
function onCanvasMouseDown(e) {
  if (e.target.classList.contains('flow-canvas-box') || e.target.classList.contains('flow-grid') || e.target.classList.contains('flow-canvas-inner')) {
    isPanningActive.value = true
    panStart = { x: e.clientX, y: e.clientY, px: panX.value, py: panY.value }
    selectedNode.value = null
    selectedEdge.value = -1
  }
}

// === 全局鼠标移动 ===
function onCanvasMouseMove(e) {
  // 节点拖拽
  if (draggingNode.value) {
    const pos = screenToCanvas(e.clientX, e.clientY)
    draggingNode.value.x = pos.x - draggingOffset.x
    draggingNode.value.y = pos.y - draggingOffset.y
  }
  // 连线拖拽
  if (draggingConn.value) {
    const pos = screenToCanvas(e.clientX, e.clientY)
    draggingConn.value.mouseX = pos.x
    draggingConn.value.mouseY = pos.y
    const from = nodePortPos(draggingConn.value.from, 'out')
    const dx = Math.abs(pos.x - from.x) * 0.5
    dragPath.value = `M ${from.x} ${from.y} C ${from.x + dx} ${from.y}, ${pos.x - dx} ${pos.y}, ${pos.x} ${pos.y}`

    // 检测当前鼠标是否悬停在某个可连接的节点上
    const target = findConnTarget(pos.x, pos.y)
    connTargetId.value = target ? target.id : null
  }
  // 画布平移
  if (isPanningActive.value) {
    panX.value = panStart.px + (e.clientX - panStart.x)
    panY.value = panStart.py + (e.clientY - panStart.y)
  }
}

// === 查找连线目标节点 ===
function findConnTarget(mx, my) {
  return nodes.value.find(n => {
    if (n.id === draggingConn.value?.from || n.type === 'start') return false
    const nt = nodeTypeMap.value[n.type]
    const w = nt?.w || 200, h = nt?.h || 80
    return mx >= n.x - 5 && mx <= n.x + w + 5 && my >= n.y - 5 && my <= n.y + h + 5
  })
}

// === 全局鼠标释放 ===
function onMouseUpGlobal(e) {
  // 节点拖拽结束
  if (draggingNode.value) {
    draggingNode.value = null
    draggingNodeId.value = null
  }
  // 连线拖拽结束
  if (draggingConn.value) {
    const pos = screenToCanvas(e.clientX, e.clientY)
    const target = findConnTarget(pos.x, pos.y)
    if (target) {
      const exists = connections.value.some(c => c.from === draggingConn.value.from && c.to === target.id)
      if (!exists) {
        connections.value.push({ from: draggingConn.value.from, to: target.id })
      }
    }
    draggingConn.value = null
    dragPath.value = ''
    connTargetId.value = null
  }
  // 平移结束
  isPanningActive.value = false
}

// === 滚轮缩放（以鼠标为中心） ===
function onWheel(e) {
  e.preventDefault()
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  const newZoom = Math.max(0.3, Math.min(2, zoom.value + delta))
  // 以鼠标位置为中心缩放
  const canvasEl = document.querySelector('.flow-canvas-box')
  if (canvasEl) {
    const rect = canvasEl.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const scaleRatio = newZoom / zoom.value
    panX.value = mx - (mx - panX.value) * scaleRatio
    panY.value = my - (my - panY.value) * scaleRatio
  }
  zoom.value = newZoom
}

function zoomIn() { zoom.value = Math.min(2, zoom.value + 0.1) }
function zoomOut() { zoom.value = Math.max(0.3, zoom.value - 0.1) }
function resetView() { zoom.value = 1; panX.value = 0; panY.value = 0 }

// === 自动排列 ===
function autoArrange() {
  if (!nodes.value.length) return
  const startNode = nodes.value.find(n => n.type === 'start')
  if (!startNode) return
  const levels = {}
  const queue = [{ id: startNode.id, level: 0 }]
  const visited = new Set()
  while (queue.length) {
    const { id, level } = queue.shift()
    if (visited.has(id)) continue
    visited.add(id)
    levels[id] = Math.max(levels[id] || 0, level)
    connections.value.filter(c => c.from === id).forEach(c => {
      if (!visited.has(c.to)) queue.push({ id: c.to, level: level + 1 })
    })
  }
  // 未连接的节点放在最右侧
  nodes.value.forEach(n => {
    if (!(n.id in levels)) levels[n.id] = Object.keys(levels).length || 0
  })
  const byLevel = {}
  nodes.value.forEach(n => {
    const lv = levels[n.id] || 0
    if (!byLevel[lv]) byLevel[lv] = []
    byLevel[lv].push(n)
  })
  const xStep = 280, yStep = 130, startX = 80, startY = 80
  Object.keys(byLevel).sort((a, b) => a - b).forEach(lv => {
    const group = byLevel[lv]
    group.forEach((n, i) => {
      n.x = startX + Number(lv) * xStep
      n.y = startY + i * yStep
    })
  })
}

// === 保存/加载/清空 ===
function saveFlow() {
  const name = flowName.value || 'default'
  const data = {
    name,
    nodes: nodes.value.map(n => {
      const { _status, _output, ...config } = n
      return config
    }),
    connections: connections.value.map(c => ({ ...c })),
    savedAt: new Date().toISOString()
  }
  localStorage.setItem('flow_' + name, JSON.stringify(data))
  localStorage.setItem('flow_last', name)
  refreshSavedFlows()
  flowResult.value = `💾 已保存「${name}」: ${nodes.value.length} 个节点, ${connections.value.length} 条连线`
}

function loadFlow() {
  const name = flowName.value || 'default'
  const key = 'flow_' + name
  const raw = localStorage.getItem(key)
  if (!raw) { flowResult.value = `未找到保存的工作流「${name}」`; return }
  try {
    const data = JSON.parse(raw)
    clearFlow()
    flowName.value = data.name || name
    data.nodes.forEach(n => {
      nodes.value.push({ ...n, _status: '', _output: '' })
      const num = parseInt(n.id.split('-').pop())
      if (num > nodeCounter) nodeCounter = num
    })
    if (data.connections) {
      data.connections.forEach(c => connections.value.push({ ...c }))
    }
    flowResult.value = `📂 已加载「${data.name || name}」: ${nodes.value.length} 个节点, ${connections.value.length} 条连线`
  } catch (e) {
    flowResult.value = `加载失败: ${e.message}`
  }
}

function clearFlow() {
  if (!confirm('确定清空画布？')) return
  clearFlowSilent()
}

function clearFlowSilent() {
  nodes.value = []
  connections.value = []
  selectedNode.value = null
  selectedEdge.value = -1
  flowResult.value = ''
  debugState.value.execHistory = []
  localStorage.removeItem('flow_last')
  localStorage.removeItem('flow_last_result')
  localStorage.removeItem('flow_result_list')
  resultList.value = []
  selectedResultId.value = null
}

// === 任务列表 ===
function refreshSavedFlows() {
  const flows = []
  // 先添加内置模板
  builtinFlows.forEach(t => {
    flows.push({
      name: t.name,
      icon: t.icon,
      nodeCount: 5,
      connCount: 5,
      savedAt: '内置模板',
      builtin: true,
      _key: null
    })
  })
  // 再添加 localStorage 中的用户保存的工作流（跳过与内置模板同名的）
  const builtinNames = builtinFlows.map(t => t.name)
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key && key.startsWith('flow_') && key !== 'flow_last') {
      try {
        const data = JSON.parse(localStorage.getItem(key))
        const name = data.name || key.slice(5)
        if (builtinNames.includes(name)) continue // 跳过与内置模板同名的
        const d = new Date(data.savedAt)
        flows.push({
          name,
          nodeCount: data.nodes?.length || 0,
          connCount: data.connections?.length || 0,
          savedAt: `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`,
          builtin: false,
          _key: key
        })
      } catch {}
    }
  }
  // 内置模板排前面，用户保存的按时间倒序
  const userFlows = flows.filter(f => !f.builtin).sort((a, b) => b.savedAt.localeCompare(a.savedAt))
  savedFlows.value = [...flows.filter(f => f.builtin), ...userFlows]
}

function switchToTaskList() {
  refreshSavedFlows()
  taskPage.value = 1
  section.value = 'tasklist'
}

function loadSavedFlow(name) {
  // 检查是否为内置模板
  const builtin = builtinFlows.find(t => t.name === name)
  if (builtin) {
    loadWeatherFlow()
    refreshSavedFlows()
    return
  }
  const key = 'flow_' + name
  const raw = localStorage.getItem(key)
  if (!raw) { refreshSavedFlows(); return }
  try {
    const data = JSON.parse(raw)
    nodes.value = []
    connections.value = []
    selectedNode.value = null
    selectedEdge.value = -1
    flowName.value = data.name || name
    data.nodes.forEach(n => {
      nodes.value.push({ ...n, _status: '', _output: '' })
      const num = parseInt(n.id.split('-').pop())
      if (num > nodeCounter) nodeCounter = num
    })
    if (data.connections) {
      data.connections.forEach(c => connections.value.push({ ...c }))
    }
    localStorage.setItem('flow_last', name)
    section.value = 'flow'
    flowResult.value = `📂 已加载「${data.name || name}」: ${nodes.value.length} 个节点, ${connections.value.length} 条连线`
  } catch (e) {
    flowResult.value = `加载失败: ${e.message}`
  }
}

// 编辑模式：加载后自动选中第一个可配置节点并打开配置面板
function editSavedFlow(name) {
  // 检查是否为内置模板
  const builtin = builtinFlows.find(t => t.name === name)
  if (builtin) {
    loadWeatherFlow()
  } else {
    const key = 'flow_' + name
    const raw = localStorage.getItem(key)
    if (!raw) { refreshSavedFlows(); return }
    try {
      const data = JSON.parse(raw)
      nodes.value = []
      connections.value = []
      selectedNode.value = null
      selectedEdge.value = -1
      flowName.value = data.name || name
      data.nodes.forEach(n => {
        nodes.value.push({ ...n, _status: '', _output: '' })
        const num = parseInt(n.id.split('-').pop())
        if (num > nodeCounter) nodeCounter = num
      })
      if (data.connections) {
        data.connections.forEach(c => connections.value.push({ ...c }))
      }
      localStorage.setItem('flow_last', name)
    } catch (e) {
      flowResult.value = `加载失败: ${e.message}`
      return
    }
  }

  // 自动选中第一个可配置节点（优先选择有参数的节点，如 start/http/llm）
  const firstConfigurable = nodes.value.find(n => n.type === 'start') || nodes.value.find(n => n.type === 'http') || nodes.value.find(n => n.type === 'llm') || nodes.value[0]
  if (firstConfigurable) {
    selectedNode.value = firstConfigurable.id
  }
  // 打开节点配置面板
  configTab.value = 'node'
  section.value = 'flow'
  flowResult.value = `✏️ 编辑模式 - 「${flowName.value}」\n已选中节点「${firstConfigurable?.label}」，在右侧面板修改参数。\n修改后点击「💾 保存」以保存更改。`
}

function deleteSavedFlow(name) {
  // 内置模板不可删除
  if (builtinFlows.some(t => t.name === name)) {
    alert('内置模板不可删除')
    return
  }
  if (!confirm(`确定删除任务「${name}」？`)) return
  localStorage.removeItem('flow_' + name)
  if (localStorage.getItem('flow_last') === name) {
    localStorage.removeItem('flow_last')
  }
  refreshSavedFlows()
}

// === 键盘删除 ===
function onKeyDown(e) {
  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return
    if (selectedNode.value) {
      e.preventDefault()
      removeNode(selectedNode.value)
    } else if (selectedEdge.value >= 0) {
      e.preventDefault()
      removeEdge(selectedEdge.value)
    }
  }
}

// === 执行引擎 ===
async function runFlow() {
  const startNode = nodes.value.find(n => n.type === 'start')
  if (!startNode) { flowResult.value = '请添加开始节点'; return }
  const endNode = nodes.value.find(n => n.type === 'end')
  if (!endNode) { flowResult.value = '请添加结束节点'; return }
  if (!connections.value.length) { flowResult.value = '请添加连线'; return }

  nodes.value.forEach(n => { n._status = ''; n._output = '' })
  debugState.value.execHistory = []
  debugState.value.isStepping = false
  tracePage.value = 1

  // 初始化变量池
  variablePool.value = {
    sys: {
      user_id: 'user_demo',
      workflow_id: 'wf_' + Date.now(),
      workflow_run_id: 'run_' + Date.now(),
      timestamp: Date.now()
    },
    env: {},
    input: { query: topic.value || '北京' },
    nodes: {}
  }

  const visited = new Set()
  const queue = [startNode.id]
  const execLog = []

  while (queue.length) {
    const nodeId = queue.shift()
    if (visited.has(nodeId)) continue
    visited.add(nodeId)
    const node = nodes.value.find(n => n.id === nodeId)
    if (!node) continue

    // 检查断点
    if (debugState.value.breakpoints.includes(nodeId) && visited.size > 1) {
      debugState.value.paused = true
      selectedNode.value = nodeId
      configTab.value = 'vars'
      flowResult.value = `⏸ 已暂停在断点: ${node.label}（点击单步继续）`
      debugState.value.stepQueue = queue
      debugState.value.isStepping = true
      return
    }

    node._status = 'running'
    const t0 = performance.now()
    await new Promise(r => setTimeout(r, 400))

    try {
      // 记录解析后的输入
      const resolvedConfig = resolveNodeConfig(node, variablePool.value)
      // 执行节点
      const output = await executeNode(node, variablePool.value)
      const duration = performance.now() - t0

      // 将结构化输出写入变量池
      variablePool.value.nodes[node.id] = output
      node._output = formatNodeOutput(output)
      execLog.push(`${node.icon} ${node.label}: ${node._output.substring(0, 80)}`)
      node._status = 'done'

      // 记录执行历史
      debugState.value.execHistory.push({
        nodeId: node.id, nodeType: node.type, nodeLabel: node.label,
        icon: node.icon, timestamp: Date.now(), duration,
        input: { config: resolvedConfig, pool: { input: variablePool.value.input } },
        output: output, error: null, _expanded: false
      })

      const next = connections.value.filter(c => c.from === nodeId).map(c => c.to)
      next.forEach(id => { if (!visited.has(id)) queue.push(id) })
    } catch (e) {
      node._status = 'error'
      const duration = performance.now() - t0
      debugState.value.execHistory.push({
        nodeId: node.id, nodeType: node.type, nodeLabel: node.label,
        icon: node.icon, timestamp: Date.now(), duration,
        input: null, output: null, error: e.message, _expanded: true
      })
      configTab.value = 'trace'
      flowResult.value = `执行失败于「${node.label}」: ${e.message}`
      saveExecResult()
      return
    }
  }

  flowResult.value = `✓ 工作流执行完成，经过 ${visited.size} 个节点\n${execLog.join('\n')}`
  saveExecResult()
}

// === 后端工作流执行（WebSocket 实时推送） ===
async function runFlowBackend() {
  const startNode = nodes.value.find(n => n.type === 'start')
  if (!startNode) { flowResult.value = '请添加开始节点'; return }
  const endNode = nodes.value.find(n => n.type === 'end')
  if (!endNode) { flowResult.value = '请添加结束节点'; return }
  if (!connections.value.length) { flowResult.value = '请添加连线'; return }

  nodes.value.forEach(n => { n._status = ''; n._output = '' })
  wfNodeRuns.value = []
  wfError.value = ''
  tracePage.value = 1

  if (wfUnsub.value) {
    try { wfUnsub.value() } catch {}
    wfUnsub.value = null
  }

  const graph = {
    nodes: nodes.value.map(n => ({
      id: n.id,
      type: n.type,
      data: buildNodeConfig(n),
    })),
    edges: connections.value.map(c => ({ source: c.from, target: c.to })),
  }

  const wfPayload = {
    name: flowName.value || '未命名工作流',
    graph,
  }

  try {
    const saveRes = await fetch('/api/workflows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(wfPayload),
    })
    if (!saveRes.ok) {
      const d = await saveRes.json().catch(() => ({}))
      throw new Error(d.error || `保存工作流失败 (${saveRes.status})`)
    }
    const { id: wfId } = await saveRes.json()

    const startInput = topic.value || ''
    const runRes = await fetch(`/api/workflows/${wfId}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs: { input: startInput } }),
    })
    if (!runRes.ok) {
      const d = await runRes.json().catch(() => ({}))
      throw new Error(d.error || `启动工作流失败 (${runRes.status})`)
    }
    const { task_id } = await runRes.json()
    wfTaskId.value = task_id
    wfRunning.value = true
    flowResult.value = '⏳ 工作流已提交，等待执行...'

    const handleUpdate = (msg) => {
      const task = msg.task || {}
      wfNodeRuns.value = task.node_runs || []
      if (msg.type === 'task_update') {
        const runningNode = (task.node_runs || []).find(r => r.status === 'running')
        if (runningNode) {
          flowResult.value = `⏳ 执行中: ${runningNode.title || runningNode.id}...`
        }
      } else if (msg.type === 'task_done') {
        wfRunning.value = false
        if (task.status === 'completed') {
          const outputs = task.result || {}
          const outputLines = []
          for (const [key, val] of Object.entries(outputs)) {
            const v = typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val)
            outputLines.push(`【${key}】\n${v}`)
          }
          const outputText = outputLines.join('\n\n')
          flowResult.value = `✅ 工作流执行完成\n共 ${(task.node_runs || []).length} 个节点\n\n--- 输出 ---\n${outputText || '（无输出变量）'}`
          try { wfUnsub.value?.() } catch {}
          wfUnsub.value = null
          saveExecResult()
        } else if (task.status === 'failed') {
          flowResult.value = `❌ 执行失败: ${task.error || '未知错误'}`
          wfError.value = task.error || '执行失败'
          try { wfUnsub.value?.() } catch {}
          wfUnsub.value = null
        } else if (task.status === 'cancelled') {
          flowResult.value = '⏹️ 已取消'
          try { wfUnsub.value?.() } catch {}
          wfUnsub.value = null
        }
      }
    }

    if (wsManager.status === 'connected') {
      wfUnsub.value = wsManager.subscribe(task_id, handleUpdate)
    } else {
      const es = new EventSource(`/api/agent/stream/${task_id}`)
      es.onmessage = (e) => {
        try {
          const task = JSON.parse(e.data)
          handleUpdate({ type: 'task_update', task })
        } catch {}
      }
      es.addEventListener('done', (e) => {
        try {
          const task = JSON.parse(e.data)
          handleUpdate({ type: 'task_done', task })
        } catch {}
        es.close()
      })
      es.addEventListener('error', () => { es.close() })
      wfUnsub.value = () => es.close()
    }
  } catch (e) {
    wfRunning.value = false
    wfError.value = e.message
    flowResult.value = `❌ 错误: ${e.message}`
  }
}

function buildNodeConfig(node) {
  const typeMap = {
    start: {
      variables: [{ variable: 'input', default: '' }],
    },
    llm: {
      model: 'model',
      temperature: 'temperature',
      systemPrompt: 'system_prompt',
      userPrompt: 'prompt',
    },
    http: {
      method: 'method',
      url: 'url',
      headers: 'headers',
      body: 'body',
    },
    code: {
      code: 'code',
      language: 'language',
    },
    template: {
      templateText: 'template',
    },
    condition: {
      conditions: 'conditions',
      trueLabel: 'true_label',
      falseLabel: 'false_label',
    },
    variable: {
      varName: 'var_name',
      varValue: 'var_value',
    },
    knowledge: {
      query: 'query',
      topK: 'top_k',
    },
    tool: {
      toolName: 'skill_id',
      toolInput: 'input',
    },
    end: {
      outputVar: 'output_var',
    },
  }
  const mapping = typeMap[node.type] || {}
  const cfg = {}
  for (const [from, to] of Object.entries(mapping)) {
    if (node[from] !== undefined) {
      let val = node[from]
      if (from === 'headers' && typeof val === 'string') {
        try { val = JSON.parse(val) } catch { val = {} }
      }
      cfg[to] = val
    }
  }
  if (node.type === 'end' && node.outputVar) {
    cfg.outputs = [{ name: 'output', value: node.outputVar }]
  }
  return cfg
}

// === 逐步执行 ===
async function stepRun() {
  // 如果未开始逐步执行，初始化
  if (!debugState.value.isStepping || debugState.value.stepQueue.length === 0) {
    const startNode = nodes.value.find(n => n.type === 'start')
    if (!startNode) { flowResult.value = '请添加开始节点'; return }
    if (!connections.value.length) { flowResult.value = '请添加连线'; return }

    nodes.value.forEach(n => { n._status = ''; n._output = '' })
    debugState.value.execHistory = []
    debugState.value.isStepping = true
    debugState.value.paused = false

    variablePool.value = {
      sys: {
        user_id: 'user_demo',
        workflow_id: 'wf_' + Date.now(),
        workflow_run_id: 'run_' + Date.now(),
        timestamp: Date.now()
      },
      env: {},
      input: { query: topic.value || '北京' },
      nodes: {}
    }
    debugState.value.stepQueue = [startNode.id]
    flowResult.value = '调试模式已启动，点击「单步」逐步执行'
    configTab.value = 'vars'
  }

  if (!debugState.value.stepQueue.length) {
    flowResult.value = '✓ 逐步执行完成'
    debugState.value.isStepping = false
    return
  }

  const nodeId = debugState.value.stepQueue.shift()
  const node = nodes.value.find(n => n.id === nodeId)
  if (!node) { stepRun(); return }

  node._status = 'running'
  const t0 = performance.now()
  await new Promise(r => setTimeout(r, 300))

  try {
    const resolvedConfig = resolveNodeConfig(node, variablePool.value)
    const output = await executeNode(node, variablePool.value)
    const duration = performance.now() - t0

    variablePool.value.nodes[node.id] = output
    node._output = formatNodeOutput(output)
    node._status = 'done'

    debugState.value.execHistory.push({
      nodeId: node.id, nodeType: node.type, nodeLabel: node.label,
      icon: node.icon, timestamp: Date.now(), duration,
      input: { config: resolvedConfig },
      output: output, error: null, _expanded: false
    })

    // 加入下游节点
    const next = connections.value.filter(c => c.from === nodeId).map(c => c.to)
    debugState.value.stepQueue.push(...next)

    flowResult.value = `⏭ 已执行: ${node.icon} ${node.label} (${duration.toFixed(0)}ms)\n剩余 ${debugState.value.stepQueue.length} 个节点待执行`
    selectedNode.value = nodeId
    configTab.value = 'vars'
  } catch (e) {
    node._status = 'error'
    const duration = performance.now() - t0
    debugState.value.execHistory.push({
      nodeId: node.id, nodeType: node.type, nodeLabel: node.label,
      icon: node.icon, timestamp: Date.now(), duration,
      input: null, output: null, error: e.message, _expanded: true
    })
    configTab.value = 'trace'
    flowResult.value = `执行失败: ${e.message}`
    debugState.value.isStepping = false
  }
}

// === 单节点测试 ===
async function testSingleNode() {
  if (!selectedNodeData.value) return
  const node = selectedNodeData.value
  if (node.type === 'end') return

  const t0 = performance.now()
  node._status = 'running'
  await new Promise(r => setTimeout(r, 200))

  try {
    const resolvedConfig = resolveNodeConfig(node, variablePool.value)
    const output = await executeNode(node, variablePool.value)
    const duration = performance.now() - t0

    node._output = formatNodeOutput(output)
    node._status = 'done'

    debugState.value.execHistory.push({
      nodeId: node.id, nodeType: node.type, nodeLabel: node.label,
      icon: node.icon, timestamp: Date.now(), duration,
      input: { config: resolvedConfig },
      output: output, error: null, _expanded: true
    })

    configTab.value = 'trace'
    flowResult.value = `🔍 单节点测试: ${node.icon} ${node.label} (${duration.toFixed(0)}ms)`
  } catch (e) {
    node._status = 'error'
    const duration = performance.now() - t0
    debugState.value.execHistory.push({
      nodeId: node.id, nodeType: node.type, nodeLabel: node.label,
      icon: node.icon, timestamp: Date.now(), duration,
      input: null, output: null, error: e.message, _expanded: true
    })
    configTab.value = 'trace'
    flowResult.value = `测试失败: ${e.message}`
  }
}

// === 断点切换 ===
function toggleBreakpoint() {
  if (!selectedNodeData.value) return
  const nodeId = selectedNodeData.value.id
  const idx = debugState.value.breakpoints.indexOf(nodeId)
  if (idx >= 0) {
    debugState.value.breakpoints.splice(idx, 1)
  } else {
    debugState.value.breakpoints.push(nodeId)
  }
}

// === 追踪数据格式化 ===
function formatTraceData(data) {
  if (!data) return 'null'
  if (typeof data === 'string') return data
  try { return JSON.stringify(data, null, 2) } catch { return String(data) }
}

async function executeNode(node, pool) {
  // 先解析节点配置中的变量引用
  const cfg = resolveNodeConfig(node, pool)

  switch (node.type) {
    case 'start':
      return { input: pool.input?.query || '开始' }

    case 'end': {
      const outVal = cfg.outputVar || ''
      return { output: outVal || '流程结束' }
    }

    case 'llm': {
      const prompt = cfg.userPrompt || ''
      const sysPrompt = cfg.systemPrompt || ''
      if (!prompt) {
        return { text: `[${cfg.model}] 请配置提示词`, usage: { prompt_tokens: 0, completion_tokens: 0 } }
      }
      // 检测是否为天气播报场景：从变量池中查找天气数据
      let text = ''
      let weatherNode = null, geoNode = null
      for (const [nid, out] of Object.entries(pool.nodes || {})) {
        if (out?.body?.current?.temperature_2m !== undefined) weatherNode = nid
        if (out?.body?.results?.[0]?.latitude !== undefined) geoNode = nid
      }
      if (weatherNode) {
        const wData = pool.nodes[weatherNode].body
        const cur = wData.current || {}
        const temp = cur.temperature_2m ?? 'N/A'
        const humidity = cur.relative_humidity_2m ?? 'N/A'
        const wind = cur.wind_speed_10m ?? 'N/A'
        const code = cur.weather_code
        const wmoMap = { 0:'晴',1:'基本晴',2:'多云',3:'阴',45:'有雾',48:'雾凇',51:'小毛毛雨',53:'毛毛雨',55:'大毛毛雨',61:'小雨',63:'中雨',65:'大雨',71:'小雪',73:'中雪',75:'大雪',80:'阵雨',81:'中阵雨',82:'大阵雨',95:'雷暴',96:'雷暴冰雹',99:'强雷暴冰雹' }
        const desc = wmoMap[code] ?? '未知'
        let city = '当前城市'
        if (geoNode) {
          city = pool.nodes[geoNode].body?.results?.[0]?.name || city
        }
        text = `🌤 ${city}天气播报\n\n` +
               `天气状况：${desc}\n` +
               `温度：${temp}°C\n` +
               `湿度：${humidity}%\n` +
               `风速：${wind} m/s\n\n` +
               (temp >= 30 ? '🥵 天气炎热，注意防暑降温，建议穿轻薄透气的衣物。' :
                temp >= 20 ? '😊 天气温和舒适，适合穿短袖或薄长袖。' :
                temp >= 10 ? '🧥 天气微凉，建议穿外套或毛衣。' :
                temp <= 0 ? '🥶 天气寒冷，注意保暖，建议穿羽绒服、戴帽子和手套。' :
                '🧣 天气较冷，建议穿厚外套。') +
               (humidity > 80 ? '\n💧 湿度较高，注意防潮。' : '') +
               (wind > 10 ? '\n💨 风速较大，出行注意防风。' : '')
      } else {
        text = `[${cfg.model}] ${prompt.substring(0, 300)}`
      }
      return {
        text,
        usage: { prompt_tokens: Math.ceil((sysPrompt + prompt).length / 4), completion_tokens: Math.ceil(text.length / 4) }
      }
    }

    case 'http': {
      const url = cfg.url || ''
      if (!url || url === '未配置') {
        return { body: '未配置URL', status_code: 0, headers: {} }
      }
      try {
        const resp = await fetch(url)
        const text = await resp.text()
        let body
        try { body = JSON.parse(text) } catch { body = text }
        return {
          body,
          status_code: resp.status,
          headers: Object.fromEntries(resp.headers.entries())
        }
      } catch (e) {
        return { body: `请求失败: ${e.message}`, status_code: 0, headers: {} }
      }
    }

    case 'code': {
      if (!cfg.code) return { result: '未编写代码' }
      return { result: { success: true, data: '代码执行结果' } }
    }

    case 'template': {
      if (!cfg.template) return { text: '未配置模板' }
      return { text: cfg.template }
    }

    case 'condition': {
      const cond = cfg.condition || ''
      return { branch: cond ? 'true' : 'false' }
    }

    case 'variable': {
      return { value: cfg.varValue || '' }
    }

    case 'knowledge': {
      const topK = cfg.topK || 3
      const query = cfg.query || ''
      return {
        result: Array.from({ length: topK }, (_, i) => ({
          id: i + 1,
          score: (0.95 - i * 0.1).toFixed(2),
          content: `关于「${query.substring(0, 20)}」的检索结果 ${i + 1}`
        }))
      }
    }

    case 'tool': {
      return { output: `工具 ${node.toolName} 执行完成` }
    }

    default: return {}
  }
}

// === 任务运行（简易模式）===
async function runTask() {
  if (!topic.value.trim()) return
  running.value = true
  error.value = ''
  result.value = ''
  section.value = 'result'
  try {
    await new Promise(r => setTimeout(r, 1500 + Math.random() * 1000))
    result.value = generateReport(topic.value)
  } catch (e) {
    error.value = '生成失败：' + e.message
  } finally {
    running.value = false
  }
}

function generateReport(topic) {
  const now = new Date().toLocaleString('zh-CN')
  return `# ${topic}\n\n> 生成时间：${now}\n\n## 一、概述\n\n${topic}是一个值得深入研究的课题。本报告将从多个维度进行分析。\n\n## 二、背景分析\n\n随着技术的快速发展，${topic}已成为行业关注的焦点。\n\n**关键数据：**\n- 市场规模预计未来 3 年保持 20%+ 年增长率\n- 核心技术专利申请数量逐年上升\n\n## 三、核心要点\n\n### 3.1 技术架构\n\n核心依赖包括：\n- 大规模预训练模型\n- 领域知识图谱\n- 安全沙箱执行环境\n\n### 3.2 应用价值\n\n- **效率提升**：自动化处理重复性任务\n- **决策辅助**：基于数据分析提供智能建议\n\n## 四、发展趋势\n\n1. **技术融合**：多模态能力整合\n2. **场景下沉**：垂直行业深入\n3. **生态开放**：开源社区活跃\n\n## 五、总结与建议\n\n建议聚焦核心场景，快速验证价值闭环。\n\n---\n\n*本报告由淘飞AI任务编排系统自动生成*`
}

function copyResult() { navigator.clipboard.writeText(result.value) }
function copyResultItem(r) { navigator.clipboard.writeText(r.result || r.flowResult || '') }

// 持久化执行结果到 localStorage（追加到结果列表）
function saveExecResult() {
  try {
    const hasError = debugState.value.execHistory.some(r => r.error)
    const totalDuration = debugState.value.execHistory.reduce((s, r) => s + (r.duration || 0), 0)
    const record = {
      id: 'run_' + Date.now(),
      timestamp: Date.now(),
      flowName: flowName.value || '未命名工作流',
      result: flowResult.value,
      status: hasError ? 'error' : 'success',
      nodeCount: debugState.value.execHistory.length,
      duration: Math.round(totalDuration),
      executedAt: new Date().toLocaleString('zh-CN'),
      flowResult: flowResult.value
    }
    resultList.value.unshift(record)
    if (resultList.value.length > 50) resultList.value = resultList.value.slice(0, 50)
    resultPage.value = 1
    selectedResultId.value = null
    persistResultList()
  } catch {}
}

// 从 localStorage 恢复执行结果列表
function loadExecResult() {
  loadResultList()
}

function copyFlowResult() {
  const lines = [flowResult.value]
  debugState.value.execHistory.forEach(r => {
    lines.push(`\n${r.icon} ${r.nodeLabel} (${r.duration.toFixed(0)}ms)`)
    if (r.error) lines.push(`  错误: ${r.error}`)
    else if (r.output) lines.push(`  输出: ${formatNodeOutput(r.output)}`)
  })
  navigator.clipboard.writeText(lines.join('\n'))
}

function renderMd(text) {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

onMounted(() => {
  document.addEventListener('mouseup', onMouseUpGlobal)
  document.addEventListener('mousemove', onCanvasMouseMove)
  document.addEventListener('keydown', onKeyDown)

  // 自动加载上次保存的工作流
  const lastName = localStorage.getItem('flow_last')
  if (lastName) {
    const raw = localStorage.getItem('flow_' + lastName)
    if (raw) {
      try {
        const data = JSON.parse(raw)
        flowName.value = data.name || lastName
        data.nodes.forEach(n => {
          nodes.value.push({ ...n, _status: '', _output: '' })
          const num = parseInt(n.id.split('-').pop())
          if (num > nodeCounter) nodeCounter = num
        })
        if (data.connections) {
          data.connections.forEach(c => connections.value.push({ ...c }))
        }
        section.value = 'flow'
      } catch (e) {
        // 加载失败，忽略
      }
    }
  }

  // 恢复上次的执行结果
  loadExecResult()
})
onUnmounted(() => {
  document.removeEventListener('mouseup', onMouseUpGlobal)
  document.removeEventListener('mousemove', onCanvasMouseMove)
  document.removeEventListener('keydown', onKeyDown)
  if (wfUnsub.value) {
    try { wfUnsub.value() } catch {}
  }
})
</script>
