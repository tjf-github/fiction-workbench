# 建卡与筛选提示包（《诡秘之主》）

- prompt-os run：`atlaspack_20261119T134737_7d448ee4`（profile：`w2`）
- atlas 产物 ref 前缀：`staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json`（sha256 645ee88fa89f）
- atlas 工具版本：0.1.0；规则 sha256：475b7b713838
- 本次候选序号：39

## 任务
下面是 narrative-atlas 用纯规则抽出的“候选女性角色”。atlas 精确率约 24%：候选里有大量普通词和男性角色，
别名也经常并错（例如“姜姑娘”被并进“姜望”）。请逐个候选判断：
1. 剔除误报：不是人名的、男性角色，不建卡，写进 feedback。
2. 纠正别名：并错的别名不放进卡片，写 feedback（split_alias）；两条候选其实是同一人，写 merge_alias；碎片名写 rename。
3. 对确认是女性角色的候选建人物卡，卡片每条 item 标注 `原文` 或 `推断`。

## 输出要求
只输出 **一个 JSON 对象**，顶层只有 `cards` 和 `feedback` 两个键，不要输出任何其他文字、注释或 Markdown 包裹以外的说明。格式模板：
```json
{
  "cards": [
    {
      "kind": "character",
      "title": "角色名",
      "aliases": [
        {
          "name": "别名",
          "basis": "推断",
          "note": "词面依据：待核（补可核验引句及 ref，否则保持待核）；归属状态：待审（说明同一人依据/错并风险）"
        }
      ],
      "items": [
        {
          "field": "外貌与衣着物理结构",
          "text": "（阶段：只写可拍摄的五官/衣着/随身物件，不写空泛形容）",
          "basis": "原文",
          "source_kind": "imported",
          "confidence": "observed",
          "sources": [
            {
              "ref": "staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[0].evidence.外貌[0]",
              "raw_quote": "（与该 ref 的证据句逐字相同）"
            }
          ]
        },
        {
          "field": "说话指纹与原声标本",
          "text": "（语气/谈话习惯概括 + 原声台词定位）",
          "basis": "原文",
          "source_kind": "imported",
          "confidence": "observed",
          "sources": [
            {
              "ref": "staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[0].evidence.原声对白[0]",
              "raw_quote": "（与该 ref 的证据句逐字相同）"
            }
          ]
        },
        {
          "field": "人物心理底色与防御边界",
          "text": "（有依据的阶段驱动力或物理防御机制；禁止写负向禁令与抽象态势总结）",
          "basis": "推断",
          "source_kind": "ai_inferred",
          "confidence": "inferred",
          "sources": []
        }
      ],
      "atlas": {
        "index": 0
      }
    }
  ],
  "feedback": [
    {
      "type": "reject_not_person",
      "candidate": "候选名",
      "atlas_index": 3,
      "reason": "……",
      "judged_by": "model",
      "quotes": [
        "（原文句，逐字照抄）"
      ]
    }
  ]
}
```

### cards（staging-card.v1 子集）
- 每张卡只写 `kind`、`title`、`aliases`、`items`、`atlas.index` 五项；`atlas.index` 填下文候选的 #编号。
- `card_id`、`card_version`、`run_id`、`book_name`、`inputs`、`review` 由脚本补，不要写；卡片和条目里都不要写 `confirmed`。
- `kind` 取 `character`、`world_entry` 或 `relationship`；relationship 卡另需 `relationship.source_name/target_name`，且条目一律 `推断`（atlas 只有关系词，没有对象）。
- **W2 六段式字段对齐**：每条 item 的 `field` 必须且只能取以下六个标准大节之一：`基础身份与阶段边界` / `外貌与衣着物理结构` / `习惯动作与职业感官` / `说话指纹与原声标本` / `关系杠杆与专属面具` / `人物心理底色与防御边界`。
- **防红烧肉铁律（v3）**：只写可拍摄的物理动作、随身物件、原声台词与客观阶段边界；**严禁**写「不做第二次试探」「不顶撞也不讨好」「禁止……」等负向行为概括，**严禁**写上帝视角抽象态势总结句。
- **原声对白优先归位**：`原声对白` 或 `全文提及` 中的代表性台词优先写入 `说话指纹与原声标本`，保留人物真实口吻与语境。
- **全量原文充分利用**：下文已提供该角色的 `全文提及` 完整原文自然段（均带 `原本:L<行号>`），请通读全部段落，全面提取外貌衣着、微动作、说话标本、关系面具与心理驱动力，按阶段填满 W2 六段式（仍须严守 `raw_quote` 逐字一致，无依据不编造）。
- `basis=原文` 的条目：`source_kind=imported`，`confidence=observed`，`sources` 至少一条；`ref` 照抄下文证据句前的 ref，`raw_quote` 与该证据句**逐字一致**（整句照抄，不增删改任何字符和标点）。任一 raw_quote 不一致，整份结果会被拒收。
- `basis=推断` 的条目：`source_kind=ai_inferred`，`confidence=inferred`，`sources` 可为空数组；改名、归纳、关系都算推断。
- 同一 `field` 可有多条 item：独立特征或不同阶段分别写，每条各自标 basis/sources；模板仅演示结构，不设固定字数，不要求凑足条数，无证据不补条。
- 阶段范围：每条 item 的 `text` 注明有依据的阶段/时间范围（早期／晋升后／近期等，有依据才写）；无法确定就写“阶段不明”。不得把早期证据写成当前状态，未知阶段不得凭人物章节跨度补事实，也不得推定有后期发展；总结跨阶段时注明或拆条。
- 具体情境与行动界限：已抽到的具体场景、顾虑、退出或界限证据，必须在对应 item 的 `text` 里保留场景范围（例如「该次聚会中……」「面对该请求时……」），不得只收成「谨慎」「冷静」「细心」这类空标签，也不得把单次情境写成无时态的习惯通例。无足够依据时宁可保留场景并写「阶段不明」，也不要抽空概括。反例：把「该次聚会上，她压低声音，在对方追问前先切断话题」只写成「谨慎」。
- 入卡先核主语：先判断该句描述的对象是不是这个人，再决定能否写入对应 field。反例：把「看见一位黑发褐瞳」当成她的外貌；把牌面「正义女神」当成她的性格；把「通过她掌握了哥哥和妹妹」当成她的家人。对象不是此人的句子不要入卡。
- 称号与身份：「正义小姐」等称呼可作称号或 gender 证据，不得单独支撑身份阶段。
- 能力默认指途径／序列及其界限；画画、厨艺等日常技艺若写必须标明是日常技艺，且不得当成非凡天赋。
- 别名词面：仅在 atlas.aliases 列表中出现，不足以证明词面来自原文。`note` 分写 `词面依据：…` 与 `归属状态：…`；无可核验原文引句及 ref 时，词面保持“待核”，有引句时写清引句、ref 及待核依据，不把模型自述当已核验。
- 别名归属：`aliases` 每项 `basis` 一律写 `推断`，`note` 的归属状态写“待审”，并说明同一人依据或错并风险；词面出现不等于同一人，归属须用户审核，不因词面有引句自动确认。
- 下文 traits 已按候选完整列出，不要重复抄写成第二份词表；特征词只是机械命中线索，不能代替逐字 evidence 或证明词的归属。
- 不要写 `sources[].chapter` 或 `sources[].line`：产物带章节号/原文行号时脚本会自动填，没有时不得猜。

### feedback（atlas-feedback.v1 的 entries 子集）
- `type` 取：reject_not_person、reject_male、split_alias、merge_alias、rename、missed。
- 每条写 `type`、`candidate`（atlas 中的名字；missed 写原文中的名字）、`reason`、`judged_by`（固定 `model`）、`quotes`；有对应候选时写 `atlas_index`；split_alias/merge_alias 写 `alias`；rename 在 `suggested` 写全名。
- 每条反馈都必须带非空 `quotes`（至少一句支持判断的原文；缺失或为空整份结果会被拒收）；每句必须是下文证据句或书原文的逐字片段。
- 不要写 `confirmed`：所有反馈都只是建议，由用户逐条确认。

## 候选角色

### #39 辛西娅
- atlas 别名（未核实，可能并错）：无
- gender=protagonist gender_confidence=0.99 score=12.55 mentions=105 出现章节数=14，点名纳入
- 人物级粗章节跨度：第623章—第1228章（仅出现范围，非逐句出处或状态有效期）
- 特征 外貌：美丽
- 特征 身份：小姐、秘书
- 特征 服饰：项链
- 特征 身体部位：眼角、脸颊
- 特征 能力：擅长
- 证据句（ref → 原文）：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[0]`〔第623章 / 原本:L54661〕 “在这里，熟悉上将阁下的只有三位，一是他的秘书，吕尔安中校，他属于军情九处，负有监督上将阁下的责任，他应该用过很多名字，我不清楚这是不是他的真实姓名，二是上将阁下在这里的情妇，一位叫做辛西娅的美丽小姐，她的祖先据说是贵族，被剥夺爵位，流放到了这里，三是奥拉维的总督奥斯顿·利维特，他是上将阁下最小的那位弟弟，上议院的利维特伯爵是他们的兄长。”
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[1]`〔第623章 / 原本:L54664〕 “我们已经准备好了，这是他的照片，这是他隐蔽处的身体特征描述，这是他的口音特点，这是他的用词习惯，这是他对不同事件的不同反应和态度，这是他与吕尔安、辛西娅、奥斯顿等人相处的细节性内容……”比尔特心中一喜，当即拿出了那来源于艾弥留斯·利维特上将的诸多资料。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[2]`〔第628章 / 原本:L55072〕 身体状况不佳，有一定的异常反应，是艾弥留斯上将为之前那个流浪汉替身准备的借口，以帮助他逃避辛西娅的亲近要求而不暴露问题，克莱恩为了增强说服力，故意用“无面人”的技巧给出了“证据”。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[3]`〔第628章 / 原本:L55073〕 辛西娅嘴巴张开，险些尖叫，还好，她及时伸掌，将嗓音堵了回去。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[4]`〔第634章 / 原本:L55613〕 “上将阁下被天体教派刺杀，辛西娅小姐遇害，吕尔安秘书受伤，将军卫队损失了不少人。”
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[5]`〔第634章 / 原本:L55617〕 现在，辛西娅小姐遇害，吕尔安秘书受伤，奥斯顿·利维特被解除了总督职务……比尔特表情呆滞地动了动嘴角。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.外貌[0]`〔第623章 / 原本:L54661〕 一位叫做辛西娅的美丽小姐
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.外貌[1]`〔第631章 / 原本:L55307〕 辛西娅涕泪横流的美丽脸庞彻底定格
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身份[0]`〔第623章 / 原本:L54661〕 一位叫做辛西娅的美丽小姐
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身份[1]`〔第624章 / 原本:L54804〕 不能与辛西娅小姐有太过亲密的接触
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身份[2]`〔第634章 / 原本:L55598〕 你是怎么隐瞒过艾弥留斯上将重点提到的吕尔安秘书、奥斯顿总督和辛西娅小姐的
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身份[3]`〔第634章 / 原本:L55613〕 辛西娅小姐遇害
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.服饰[0]`〔第625章 / 原本:L54911〕 辛西娅取掉这项链
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.服饰[1]`〔第632章 / 原本:L55392〕 天体教派的目的是借助辛西娅借助普通物品状态的“繁衍项链”
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.服饰[2]`〔第632章 / 原本:L55394〕 被我三次拒绝的辛西娅因为体内‘繁衍项链’粉末的污染力量难以得到排解
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.服饰[3]`〔第632章 / 原本:L55419〕 最开始只想把‘繁衍项链’借给辛西娅
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身体部位[0]`〔第626章 / 原本:L54955〕 眼角余光看见辛西娅无声离去并顺手关上房门
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身体部位[1]`〔第629章 / 原本:L55228〕 辛西娅脸颊酡红地俯视着克莱恩
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.能力[0]`〔第630章 / 原本:L55251〕 确认辛西娅变异成的怪物究竟擅长什么后
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[0]`〔第623章 / 原本:L54661〕 “在这里，熟悉上将阁下的只有三位，一是他的秘书，吕尔安中校，他属于军情九处，负有监督上将阁下的责任，他应该用过很多名字，我不清楚这是不是他的真实姓名，二是上将阁下在这里的情妇，一位叫做辛西娅的美丽小姐，她的祖先据说是贵族，被剥夺爵位，流放到了这里，三是奥拉维的总督奥斯顿·利维特，他是上将阁下最小的那位弟弟，上议院的利维特伯爵是他们的兄长。”
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[1]`〔第623章 / 原本:L54664〕 “我们已经准备好了，这是他的照片，这是他隐蔽处的身体特征描述，这是他的口音特点，这是他的用词习惯，这是他对不同事件的不同反应和态度，这是他与吕尔安、辛西娅、奥斯顿等人相处的细节性内容……”比尔特心中一喜，当即拿出了那来源于艾弥留斯·利维特上将的诸多资料。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[2]`〔第624章 / 原本:L54804〕 那张纸上的条款很简单，只有那么几条，大致约束了格尔曼·斯帕罗扮演艾弥留斯·利维特时的行为，包括但不限于不能主动暴露问题，不能利用上将身份做不利于艾弥留斯本人的事情，不能与辛西娅小姐有太过亲密的接触，等等，等等。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[3]`〔第624章 / 原本:L54806〕 “如果辛西娅小姐想和我有亲密接触呢？”
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[4]`〔第624章 / 原本:L54807〕 他的潜台词是表现得太过疏离和抗拒容易被辛西娅看出问题，询问该怎么把握一个度。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[5]`〔第625章 / 原本:L54884〕 这不是说奥斯顿总督和辛西娅小姐没有秘书先生熟悉艾弥留斯上将，而是奥斯顿作为弟弟，即使发现什么问题，得到暗示后，也可能会帮着兄长隐瞒，同样，身为情妇，辛西娅依附上将，有帮助遮掩的倾向。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[6]`〔第625章 / 原本:L54885〕 当然，不排除辛西娅是间谍，或被间谍利用的可能，但都没有本身就是监督者的吕尔安危险。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[7]`〔第625章 / 原本:L54901〕 她大概二十出头，金发润泽披下，蓝眼望来之际，似有光辉暗藏，在充满女性柔美的同时又残留着几分少女感，正是艾弥留斯上将的情妇辛西娅。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[8]`〔第625章 / 原本:L54903〕 辛西娅投入他的怀里，踮起脚尖，脸颊贴脸颊地低声笑道：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[9]`〔第625章 / 原本:L54907〕 “很好。”克莱恩赞美了一声，双手有种无处安放感地轻轻推开了辛西娅。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[10]`〔第625章 / 原本:L54908〕 知道上将阁下不喜欢当着仆人们的面亲热，辛西娅顺势退开，引着克莱恩上到二楼，进入盥洗室，并准备好了浴袍。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[11]`〔第625章 / 原本:L54909〕 做完这一切，辛西娅吩咐仆人们不听见铃铛的声音不要到二楼来，然后回到卧室，脱掉全部的衣裙，换上了纯丝绸的睡袍。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[12]`〔第625章 / 原本:L54911〕 辛西娅取掉这项链，将它塞至枕头底下，然后有些羞赧有些犹豫地离开卧室，走至上将泡澡的盥洗室外，鼓起勇气拧动了把手。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[13]`〔第625章 / 原本:L54913〕 辛西娅一脸茫然地又本能拧了两下。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[14]`〔第626章 / 原本:L54920〕 多么美好的夜晚啊……如果外面没有辛西娅就好了，等下还得应付她……克莱恩叹息一声，考虑着之后怎么找借口回避亲近的事情。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[15]`〔第626章 / 原本:L54922〕 至于这是否会对上将的形象造成损害，克莱恩一点心理压力都没有，只要不让辛西娅怀疑他是假的艾弥留斯·利维特，他就算圆满完成了任务。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[16]`〔第626章 / 原本:L54927〕 不管怎么样，都必须和辛西娅打声招呼，否则会显得“艾弥留斯”上将心虚古怪……克莱恩回忆起类似房屋的格局，试图准确找到主卧室。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[17]`〔第626章 / 原本:L54928〕 就在这时，斜对面房间的门吱呀一声打开，只套了件丝绸睡袍的辛西娅走了出来。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[18]`〔第626章 / 原本:L54935〕 “嗯……辛西娅和资料里记载的有点不一样啊，不是说她成为艾弥留斯的情妇才一两年，而且大部分时候都见不到对方，在那种事情上较为放不开，每次都得上将哄着吗？今天怎么有主动勾引的倾向？
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[19]`〔第626章 / 原本:L54937〕 辛西娅眼帘低垂，原本强行鼓起的勇气在艾弥留斯的审视下一点点消失，脸庞逐渐染上了惊心动魄的红晕，心里既羞赧，又略微有些自豪。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[20]`〔第626章 / 原本:L54941〕 “……”辛西娅茫然抬头，脸上羞红依旧。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[21]`〔第626章 / 原本:L54948〕 辛西娅流露出明显的失望，但很快就收敛住了那些情绪，堆起笑容道：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[22]`〔第626章 / 原本:L54951〕 这一点和资料里一致，较为体贴，懂得体谅人……克莱恩看着辛西娅转身进屋，拉响铃铛，自己则趁这个机会，脱掉浴袍，换上了暗红的睡衣和同色的睡裤。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[23]`〔第626章 / 原本:L54952〕 辛西娅殷勤地打开书房的门，将略显杂乱的桌子简单处理了一下，然后等待女仆泡好咖啡，亲手接过，送了进来。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[24]`〔第626章 / 原本:L54955〕 眼角余光看见辛西娅无声离去并顺手关上房门，克莱恩彻底松了口气，知道今晚算是混过去了。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[25]`〔第626章 / 原本:L54956〕 主卧室内，辛西娅抿住嘴唇，从枕头底下拿出了那条项链，将只有指节大小的黑色犀牛角式物品紧握于掌心。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[26]`〔第627章 / 原本:L55036〕 天亮之后，克莱恩在辛西娅的服侍下更换好衣物，享用了丰盛的早餐，接着乘坐马车，在将军卫队簇拥里进入奥拉维海军基地。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[27]`〔第627章 / 原本:L55055〕 接下来还得应付辛西娅！
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[28]`〔第627章 / 原本:L55057〕 别墅内，辛西娅从外出探听的侍者口中知晓艾弥留斯上将即将归来。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[29]`〔第628章 / 原本:L55064〕 看见辛西娅因为有别人在，家居衣物保守，克莱恩无声松了口气，保持严肃正经的表情不变，缓步靠拢过去。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[30]`〔第628章 / 原本:L55065〕 辛西娅的笑容愈发明显，将垂落的几缕发丝撩至耳后，露出了修长白皙的脖子，上面没有项链存在的痕迹。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[31]`〔第628章 / 原本:L55066〕 见秘书吕尔安和将军卫队的成员们或前往自身居住的房间，或散开警戒屋外，克莱恩抢在辛西娅给予拥抱前，沉声说道：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[32]`〔第628章 / 原本:L55068〕 “……”辛西娅用眼神表示了自己的茫然和疑惑。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[33]`〔第628章 / 原本:L55072〕 身体状况不佳，有一定的异常反应，是艾弥留斯上将为之前那个流浪汉替身准备的借口，以帮助他逃避辛西娅的亲近要求而不暴露问题，克莱恩为了增强说服力，故意用“无面人”的技巧给出了“证据”。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[34]`〔第628章 / 原本:L55073〕 辛西娅嘴巴张开，险些尖叫，还好，她及时伸掌，将嗓音堵了回去。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[35]`〔第628章 / 原本:L55074〕 “没问题吧？需要找医生吗？”辛西娅稍有缓和，立刻紧张询问，关切之情溢于言表。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[36]`〔第628章 / 原本:L55076〕 “好，好的。”辛西娅忙引领克莱恩上到二楼，带着他进入最安静的那个房间。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[37]`〔第628章 / 原本:L55079〕 不远处的主卧室内，又担忧又失落的辛西娅泡了个热水澡，同样进入了被窝。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[38]`〔第628章 / 原本:L55082〕 将军的心里好像藏着很多事情，以至于身体都出现了一定的异常……辛西娅漫无边际地想着，思绪逐渐飘散。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[39]`〔第628章 / 原本:L55140〕 傍晚时分，他推掉了预定的晚宴，回到那栋花园别墅，看着迎面走来的辛西娅，与对方拥抱了一下。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[40]`〔第628章 / 原本:L55144〕 “我听说了，应该没事的，对吧？”辛西娅紧张问道。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[41]`〔第629章 / 原本:L55150〕 辛西娅隐隐约约能感受到艾弥留斯上将那种内敛而深沉的痛苦和无奈，没有再多说什么，只是紧紧拥抱着他，用自身的陪伴与相依给予平复心情的力量。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[42]`〔第629章 / 原本:L55172〕 主卧室内，辛西娅也已睡着。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[43]`〔第629章 / 原本:L55180〕 刚才，他不仅梦到了只穿一件丝绸睡袍的辛西娅，并与对方发生了超友谊关系，而且还梦到了他见过赤裸身体的“欢愉魔女”雪伦夫人，梦到了精致仿佛人偶的莎伦小姐，梦到了容貌还比较模糊的“正义”小姐，梦到了特莉丝奇克，梦到了特雷茜，梦到了自身见过的一位位美丽女性，然后用各种方式与她们纵情交缠。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[44]`〔第629章 / 原本:L55227〕 这是位女性，她有着金色的长发和蔚蓝的眼睛，有着高挺的鼻梁和丰润的唇瓣，正是柔美又残余几分少女感的辛西娅！
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[45]`〔第629章 / 原本:L55228〕 辛西娅脸颊酡红地俯视着克莱恩，带着几分羞涩地说道：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[46]`〔第630章 / 原本:L55233〕 看到白皙身体巨大化，长了不少瘤体和花朵，仿佛一株怪树的辛西娅，听见她那害羞低徊的请求，克莱恩忍不住打了个冷颤，根根汗毛全部竖立了起来。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[47]`〔第630章 / 原本:L55235〕 换做身在廷根面对梅高欧丝那会，克莱恩肯定会被类似的画面影响，因恐惧和慌乱短暂失去做出反应的能力，但经历过这么多事情后，他已是真正意义上的老练之人资深非凡者，在辛西娅话语入耳的同时，他左掌的手套悄然就改变了颜色。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[48]`〔第630章 / 原本:L55237〕 刹那之间，他“扭曲”了辛西娅的言语，将“将军，我想和你有一个孩子”变成了“将军，我只想和你有一个孩子”。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[49]`〔第630章 / 原本:L55238〕 这样一来，克莱恩相信围绕在树木般怪物周围的将军卫队成员和男性侍者们必然会被扭曲了意愿的辛西娅主动推开，丢到远处，获得喘息的机会。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[50]`〔第630章 / 原本:L55241〕 “腐化男爵”的“扭曲”能力无声无息发动了，但克莱恩愕然看见环绕辛西娅的那些男性们动作没有任何变化，未受到一点排斥！
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[51]`〔第630章 / 原本:L55242〕 明明已经扭曲……变异后的辛西娅竟然能直接抵御住这种影响……克莱恩瞳孔一缩，猛地向侧方跳了两步。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[52]`〔第630章 / 原本:L55251〕 他原本没想这么快使用这枚符咒，不是舍不得，而是希望缠斗一阵，确认辛西娅变异成的怪物究竟擅长什么后，再做有针对性的削弱，毕竟“第九律”没法做宽泛的限制，内容必须足够具体，比如，它无法让此地超凡失效，却可以指定其中一项非凡能力不发挥作用，要想让它的价值最大化，仔细的观察和敏锐的判断是前置条件！
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[53]`〔第630章 / 原本:L55253〕 要是“第九律”符咒不能营造出可以击杀怪物的环境，我就立刻借助它逃出别墅，将辛西娅引到外面，然后找机会祈祷，去灰雾之上用“海神权杖”做饱和覆盖式攻击！念头一闪间，不断于树枝与花朵间跳跃躲避的克莱恩低沉念出了一个古赫密斯语单词：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[54]`〔第630章 / 原本:L55257〕 他第一反应是禁止产生任何欲望，但明确知道这太过宽泛，所以想着改成禁止繁衍的欲望，毕竟辛西娅的意愿是想和艾弥留斯上将有一个孩子，她表现出来的对周围的影响也以这方面为主！
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[55]`〔第630章 / 原本:L55259〕 辛西娅之前是普通人！
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[56]`〔第630章 / 原本:L55261〕 这三个晚上，克莱恩用“灵视”和占卜等办法反复确认过多次，相信辛西娅不是非凡者。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[57]`〔第630章 / 原本:L55264〕 难道像梅高欧丝那样，通过某些仪式，成为了邪神降临的载体？不，如果有仪式，我不可能发现不了，灵性直觉会警告我不能开“灵视”，不能直视辛西娅……是她身上有什么物品和特性，让外在的力量投影了过来，所以，前面两晚没事，今晚突然异变……不管怎么样，她的可怕都来自于外界，并非本身……克莱恩在这一两秒内飞快做出判断，不再犹豫，抓住时机，低沉开口道：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[58]`〔第630章 / 原本:L55273〕 如果没有“第九律”符咒，他爆掉的何止是眼睛，说不定会变成辛西娅一样的怪物！
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[59]`〔第630章 / 原本:L55274〕 与此同时，高大树木般的辛西娅静止在了那里，身体霍然崩解，化成了一摊长着褐绿色瘤体的血肉，周围的将军卫队成员和男性侍者们扑通扑通摔倒，昏迷在了床边和地上。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[60]`〔第630章 / 原本:L55275〕 辛西娅的脑袋镶嵌在那团血肉里，口中喃喃自语道：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[61]`〔第630章 / 原本:L55283〕 辛西娅的脑袋则满是失落和迷惑地低语道：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[62]`〔第630章 / 原本:L55289〕 克莱恩怜悯地看着血肉堆里的辛西娅脑袋，往两侧张开了双臂。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[63]`〔第631章 / 原本:L55295〕 难以言喻的嗞嗞声里，辛西娅的脸蛋皱了起来，显得异常痛苦。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[64]`〔第631章 / 原本:L55298〕 克莱恩原本可以用辛西娅残留的血肉和灵体喂食“蠕动的饥饿”，但此刻只是叹息了一声，语气平和地说道：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[65]`〔第631章 / 原本:L55300〕 在他看来，辛西娅变成现在这幅模样，要么涉及邪教，要么因为某件危险的物品，与不可直视的存在发生了勾连，所以才会如此回应。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[66]`〔第631章 / 原本:L55301〕 辛西娅隐约明白了点什么，只剩一个脑袋和些许血肉的她突然流下了眼泪：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[67]`〔第631章 / 原本:L55305〕 欲望母树……天体教派……这不在我的神秘学知识范围内……克莱恩表情未变，目光怜悯地看着崩溃求救的辛西娅，再次张开了双臂，低沉开口道：
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[68]`〔第631章 / 原本:L55307〕 又是一道明净纯粹的光柱落下，辛西娅涕泪横流的美丽脸庞彻底定格。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[69]`〔第631章 / 原本:L55313〕 刚才的经历让他不敢直接“通灵”，事情的许多诡异之处则使他放弃了将辛西娅灵体带到灰雾之上“询问”的打算，而面对那种邪恶感觉无法排解且腐蚀越来越严重的情况，他只能选择让辛西娅及时获得净化，毕竟这是一个有真神的世界，死后也许确实存在天国。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[70]`〔第631章 / 原本:L55318〕 “据艾弥留斯上将的描述，吕尔安至少是序列6的非凡者，疑似‘腐化男爵’，甚至可能暗中达到了序列5……他都这么轻易被放大的欲望控制，说明借助辛西娅降临的那种力量本质极高，可为什么我只是做了个春梦……
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[71]`〔第631章 / 原本:L55321〕 “嗯，如果没有它们，作为辛西娅主要目标的我，那方面的欲望肯定会被放大到极致，这就不会只是做一场旖旎的美梦了……”克莱恩习惯性伸右手抚了下脸孔，重新变回了艾弥留斯·利维特的样子。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[72]`〔第631章 / 原本:L55323〕 上前几步，克莱恩来到辛西娅消失处，弯腰从睡床上那堆撑破的衣物里捡起了一根项链。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[73]`〔第631章 / 原本:L55325〕 “这就是导致辛西娅异变的危险物品？因为已经连接上那位不可直视的存在，它完成了使命，将所有力量灌注入了辛西娅的体内？”克莱恩根据坠子的情况和之前的经历初步做出了猜测。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[74]`〔第631章 / 原本:L55330〕 “你将这里的轻伤者全部唤醒，一部分救治剩余的人，一部分立刻调查奥拉维岛的天体教派，他们崇拜一个叫‘欲望母树’的邪神，嗯……从辛西娅周围的人查起。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[75]`〔第631章 / 原本:L55337〕 他很快有了一定的联想，因为白银城的神话传说和埃姆林·怀特对血族情况的一些描述，让他确认“月亮”途径有“繁衍繁殖”的部分权柄，这与辛西娅的意图和表现较为吻合。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[76]`〔第631章 / 原本:L55350〕 “这是辛西娅小姐的父母提供的线索。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[77]`〔第632章 / 原本:L55371〕 “你认识辛西娅吗？”
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[78]`〔第632章 / 原本:L55377〕 “辛西娅，辛西娅小姐想和上将阁下，想和您有一个具备非凡能力的孩子，被她的父母介绍，介绍给了我。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[79]`〔第632章 / 原本:L55380〕 他相信的部分是辛西娅的目的，这位美丽的小姐或许出于自身的想法，或许被别人催促逼迫，确实想要和艾弥留斯上将有一个孩子，这从她变异后执着的事情就能看出。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[80]`〔第632章 / 原本:L55382〕 而且，艾弥留斯上将是个外表严肃古板内心很重感情的人，哪怕私生子，他也肯定会喜爱和重视……这或许就是辛西娅迫切希望有个孩子的真正原因……克莱恩在心里暗自叹息了一声。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[81]`〔第632章 / 原本:L55383〕 他对福莱特·肯回答的怀疑则集中于那条“繁衍项链”的真实作用，以及天体教派在这件事情上是否有意误导了辛西娅。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[82]`〔第632章 / 原本:L55389〕 “只要辛西娅服食它磨下来的粉末，并虔诚地诵念‘欲望母树’的尊名，就可以，就可以让与她发生关系并孕育孩子成功的男性被污染！
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[83]`〔第632章 / 原本:L55392〕 天体教派的目的是借助辛西娅借助普通物品状态的“繁衍项链”，污染艾弥留斯上将，让这位鲁恩王国的军方大人物成为“欲望母树”的虔诚信徒，照顾他们教派的发展，甚至提供庇护。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[84]`〔第632章 / 原本:L55394〕 “所以，被我三次拒绝的辛西娅因为体内‘繁衍项链’粉末的污染力量难以得到排解，逐渐超过上限，最终与‘欲望母树’产生勾连，出现了看似突然的变异……
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[85]`〔第632章 / 原本:L55398〕 “我们只对辛西娅小姐和这里的仆人们做了监控，没拓展到他们的家人他们的亲属和朋友。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[86]`〔第632章 / 原本:L55417〕 在他想来，福莱特·肯的回答应该是我们自己谋划的，在接触到辛西娅，了解了她的需求，知晓了她的情夫是谁后，天体教派就大胆地有了污染海军上将艾弥留斯的想法。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[87]`〔第632章 / 原本:L55419〕 “是，是‘欲望母树’，祂，祂在梦里指使我们这么做的，我最，最开始只想把‘繁衍项链’借给辛西娅，辛西娅小姐佩戴，没打算让她服食粉末。”
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[88]`〔第632章 / 原本:L55444〕 艾弥留斯上将原本的那个流浪汉替身果然是他们杀的！为的就是让上将无法离开，从而踏入陷阱，与辛西娅发生关系，遭受污染？克莱恩瞬间将所有的事情串连在了一起。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[89]`〔第633章 / 原本:L55528〕 “你的辛西娅小姐异变成了怪物，被我净化了。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[90]`〔第634章 / 原本:L55538〕 克莱恩未做太多的隐瞒，先从奥斯顿·利维特的询问开始，然后提及梦中被神秘人警告，说不要对抗时代的潮流历史的选择，接着简单讲了下突然而来的那封电报，最后将辛西娅的异变、现场的情况、秘书的傲慢、自身的应对、后续的调查大致描述了一遍。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[91]`〔第634章 / 原本:L55553〕 “我原本没打算和替身签订契约，而是准备告知辛西娅，说出现了失控的前兆，5天内没法和她亲近，但后来一些原因让我改变了主意。”
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[92]`〔第634章 / 原本:L55555〕 当然，辛西娅提前知道5天限制后，就不会急着服食“繁衍项链”磨出的粉末，从而不会感应到“欲望母树”，出现异变……但这样一来，主动权就在天体教派手上，他们可以找别的借口，让辛西娅服食……
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[93]`〔第634章 / 原本:L55570〕 克莱恩原本还想以这次任务的难度超过了事先约定的界限做理由，索取额外的报酬，但隐约可以确认辛西娅的事情因自己而来后，已心虚地放弃了这个打算。他快速脱掉舒适的睡袍，换上燕尾正装，循着艾弥留斯的指引，从窗口跃下，在一位位守卫不知被什么“蒙”了眼睛的状况里，悄然离开了这栋花园别墅。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[94]`〔第634章 / 原本:L55598〕 “好。”比尔特对此没有异议，接着有些好奇地问道，“格尔曼先生，你是怎么隐瞒过艾弥留斯上将重点提到的吕尔安秘书、奥斯顿总督和辛西娅小姐的？”
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[95]`〔第634章 / 原本:L55613〕 “上将阁下被天体教派刺杀，辛西娅小姐遇害，吕尔安秘书受伤，将军卫队损失了不少人。”那位合作者简单描述道。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[96]`〔第634章 / 原本:L55617〕 现在，辛西娅小姐遇害，吕尔安秘书受伤，奥斯顿·利维特被解除了总督职务……比尔特表情呆滞地动了动嘴角。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[97]`〔第863章 / 原本:L73855〕 他表面是在说自己于南大陆西拜朗做生意时的遭遇，实际却回想起了孕育邪神子嗣的梅高欧丝、从天而降的恐怖陨石、想要给艾弥留斯上将生孩子的辛西娅和造成拜亚姆城外山峰坍塌的玫瑰学派天使和灵教团怪物。
  - `staging/gmzz-cynthia-002/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.全文提及[98]`〔第1228章 / 原本:L103189〕 想到这里，克莱恩突然记起了“欲望母树”借辛西娅之口说的一句话：
