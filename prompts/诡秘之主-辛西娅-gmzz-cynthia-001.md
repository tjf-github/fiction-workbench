# 建卡与筛选提示包（《诡秘之主》）

- prompt-os run：`atlaspack_20261119T105928_ea01f3c2`（profile：`w2`）
- atlas 产物 ref 前缀：`staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json`（sha256 bbac3642bd2a）
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
              "ref": "staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[0].evidence.外貌[0]",
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
              "ref": "staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[0].evidence.原声对白[0]",
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
- **原声对白优先归位**：`原声对白` 证据槽位中的代表性台词优先写入 `说话指纹与原声标本`，保留人物真实口吻与语境。
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
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[0]`〔第623章 / 原本:L54661〕 “在这里，熟悉上将阁下的只有三位，一是他的秘书，吕尔安中校，他属于军情九处，负有监督上将阁下的责任，他应该用过很多名字，我不清楚这是不是他的真实姓名，二是上将阁下在这里的情妇，一位叫做辛西娅的美丽小姐，她的祖先据说是贵族，被剥夺爵位，流放到了这里，三是奥拉维的总督奥斯顿·利维特，他是上将阁下最小的那位弟弟，上议院的利维特伯爵是他们的兄长。”
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[1]`〔第623章 / 原本:L54664〕 “我们已经准备好了，这是他的照片，这是他隐蔽处的身体特征描述，这是他的口音特点，这是他的用词习惯，这是他对不同事件的不同反应和态度，这是他与吕尔安、辛西娅、奥斯顿等人相处的细节性内容……”比尔特心中一喜，当即拿出了那来源于艾弥留斯·利维特上将的诸多资料。
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[2]`〔第628章 / 原本:L55072〕 身体状况不佳，有一定的异常反应，是艾弥留斯上将为之前那个流浪汉替身准备的借口，以帮助他逃避辛西娅的亲近要求而不暴露问题，克莱恩为了增强说服力，故意用“无面人”的技巧给出了“证据”。
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[3]`〔第628章 / 原本:L55073〕 辛西娅嘴巴张开，险些尖叫，还好，她及时伸掌，将嗓音堵了回去。
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[4]`〔第634章 / 原本:L55613〕 “上将阁下被天体教派刺杀，辛西娅小姐遇害，吕尔安秘书受伤，将军卫队损失了不少人。”
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.gender[5]`〔第634章 / 原本:L55617〕 现在，辛西娅小姐遇害，吕尔安秘书受伤，奥斯顿·利维特被解除了总督职务……比尔特表情呆滞地动了动嘴角。
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.外貌[0]`〔第623章 / 原本:L54661〕 一位叫做辛西娅的美丽小姐
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.外貌[1]`〔第631章 / 原本:L55307〕 辛西娅涕泪横流的美丽脸庞彻底定格
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身份[0]`〔第623章 / 原本:L54661〕 一位叫做辛西娅的美丽小姐
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身份[1]`〔第624章 / 原本:L54804〕 不能与辛西娅小姐有太过亲密的接触
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身份[2]`〔第634章 / 原本:L55598〕 你是怎么隐瞒过艾弥留斯上将重点提到的吕尔安秘书、奥斯顿总督和辛西娅小姐的
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身份[3]`〔第634章 / 原本:L55613〕 辛西娅小姐遇害
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.服饰[0]`〔第625章 / 原本:L54911〕 辛西娅取掉这项链
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.服饰[1]`〔第632章 / 原本:L55392〕 天体教派的目的是借助辛西娅借助普通物品状态的“繁衍项链”
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.服饰[2]`〔第632章 / 原本:L55394〕 被我三次拒绝的辛西娅因为体内‘繁衍项链’粉末的污染力量难以得到排解
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.服饰[3]`〔第632章 / 原本:L55419〕 最开始只想把‘繁衍项链’借给辛西娅
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身体部位[0]`〔第626章 / 原本:L54955〕 眼角余光看见辛西娅无声离去并顺手关上房门
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.身体部位[1]`〔第629章 / 原本:L55228〕 辛西娅脸颊酡红地俯视着克莱恩
  - `staging/gmzz-cynthia-001/atlas/诡秘之主-UTF8_female_characters.json#characters[39].evidence.能力[0]`〔第630章 / 原本:L55251〕 确认辛西娅变异成的怪物究竟擅长什么后
