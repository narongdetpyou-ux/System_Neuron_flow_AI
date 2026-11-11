# Roadmap — what to build next, in order

**Written 2026-11-01** on `main` @ `6d1f548`, after Milestone B (PR #11) and the Claude Code session hook
(PR #12). It is the working plan for Claude Code sessions and for the owner.

This file decides **what to do next, in which order, and how to know each step is done**. Why the system
is shaped this way is explained elsewhere:
- [architecture.md](architecture.md) covers layers, Core constraints, ADRs and gates.
- [design_philosophy.md](design_philosophy.md) is the owner's compass.

An older Thai planning document ("Architecture Roadmap v3") lives only in the claude.ai Project. Where it
differs, this file and architecture.md win.

## สรุปสำหรับเจ้าของโปรเจกต์

**ตอนนี้ระบบทำอะไรได้แล้ว**
- รับเคสผ่านหน้าเว็บภาษาไทยหรือ API แล้วบันทึกลงคิวถาวรก่อนตอบ
- ตัวรันงานหยิบเคสไปทำทีละเคส:
  - กฎคำสำคัญเสนอหมวด
  - AI ให้ความเห็นที่สอง
  - ถ้าสองฝ่ายเห็นไม่ตรงกัน เคสจะถูกยกให้คนดูก่อน
- ถ้าเครื่องดับกลางทาง ระบบทำต่อได้ ส่งซ้ำก็ไม่เกิดงานซ้ำ
- ยกเลิกเคสที่ยังรอคิวได้ และทุกคำขอมีรหัสคำขอ (request id) ไว้ไล่ดูใน log (ขั้น 1.2, 1.3)
- ผ่านชุดทดสอบอัตโนมัติ 477 ข้อ และเปิดใช้ออนไลน์บน Render แล้ว ระบบปิดตัวอย่างเรียบร้อย และการแก้แค่เอกสารไม่ทำให้ Render ขึ้นเวอร์ชันใหม่ (ขั้น 0.1, 0.5)
- หน้าเว็บเป็นแบบแชท: พิมพ์เคส ดูขั้นตอนก่อนส่ง กดยืนยัน แล้วติดตามใน Flow และประวัติเหตุการณ์ (ขั้น 1.6)
- หน้าเว็บบอกว่ามีเคสรอกี่เคส เคสที่รอนานสุดรอมานานเท่าไร ปกติแต่ละเคสใช้เวลาเท่าไร และเคสที่ไม่สำเร็จล้มเพราะอะไร (ขั้น 5.3)
- ถ้ามีคนแก้กฎหรือ prompt แล้วคำตอบของเคสทดสอบเคสไหนเปลี่ยน ช่องตรวจบน GitHub จะเป็นสีแดงและบอกว่าเคสไหนเปลี่ยนอะไร (ขั้น 5.2)
- ก่อนส่งเคสให้ AI ระบบปิดข้อมูลส่วนตัวที่จับรูปแบบได้ (อีเมล เบอร์โทร เลขบัตรประชาชน เลขแบบบัตรเครดิต ตัวเลขยาว และชื่อที่มีคำนำหน้า) AI เห็นแค่ป้ายแทน เช่น [PHONE] และหน้าเว็บบอกว่าปิดอะไรไปกี่จุด (ขั้น 7.1)
- ทุกครั้งที่มีการส่งโค้ด GitHub สแกนหาคีย์หรือรหัสลับที่หลุดในประวัติโค้ดทั้งหมด และที่อยู่ Sentry (DSN) ไม่อยู่ในไฟล์แล้ว อ่านจากความลับ (secret) เท่านั้น (ขั้น 7.4 ส่วนเตรียมการ)
- ส่งเส้นทางการทำงาน (trace) ของทุกเคสไป Honeycomb แล้ว: เห็นว่าแต่ละขั้นใช้เวลาเท่าไร ลองกี่ครั้ง และ AI ใช้ token เท่าไร โดยไม่ส่งข้อความเคสหรือคำตอบของ AI เปิดใช้บน Render แล้ว และเห็นเส้นทางแรกใน Honeycomb เมื่อ 4 พ.ย. 00:23 น. (ขั้น 5.1)
- มีคลังแหล่งเรียนที่ตรวจแล้ว 17 แหล่งใน 11 หัวข้อ ทุกแหล่งบอกว่าใช้ทำอะไร ระดับไหน ภาษาอะไร และควรเน้นส่วนไหน และ GitHub เปิดทุกลิงก์ทุกวันจันทร์เพื่อจับลิงก์เสีย (ขั้น 3.1)
- ผู้ช่วยแนะนำแหล่งเรียนทำงานได้แล้วผ่าน API: พิมพ์เรื่องที่อยากรู้ด้วยคำธรรมดา ได้แหล่งเรียนไม่เกิน 5 แหล่งเรียงพื้นฐานก่อน ทุกลิงก์มาจากคลัง ถ้าเรื่องอยู่นอกกรอบก็บอกตรง ๆ ว่าช่วยเรื่องไหนได้ (ขั้น 3.2) และตั้งแต่ขั้น 3.4 ใช้ได้บนหน้าเว็บ (ข้อสุดท้าย)
- มีชุดข้อสอบของผู้ช่วยแนะนำแหล่งเรียน 67 ข้อ (ไทยและอังกฤษ คำเปรียบ คำพูดอ้อม เรื่องนอกกรอบ และคำสั่งแอบแฝง) GitHub รันทุกครั้งที่ส่งโค้ด ถ้ามีลิงก์นอกคลังหรือเกิน 5 แหล่งแม้ข้อเดียว หรือคำตอบข้อไหนเปลี่ยน ช่องตรวจจะเป็นสีแดง AI จำลองหาหัวข้อถูกแค่ 2 จาก 48 ข้อ ซึ่งไม่ใช่ความแม่นยำ ส่วนผลกับ AI จริงอยู่ในข้อถัดไป (ขั้น 3.3)
- วัดผล AI จริงครั้งแรกแล้ว ฟรีผ่าน Typhoon ของ SCB 10X (เก่งภาษาไทย) เมื่อ 6 พ.ย.: รอบแรก AI ตอบไม่ได้เลย 0 จาก 5 เคส เพราะ Typhoon ไม่ทำตามช่องตั้งค่าที่ขอให้ตอบเป็น JSON แก้แล้วโดยบอกรูปแบบคำตอบเป็นคำพูดด้วย (ADR-022) หลังแก้ รันครบทั้งชุด: คัดแยกเคส AI ถูก 60 จาก 61 เคส ทั้ง 2 รอบ (กฎเดิมถูก 29) และผู้ช่วยแนะนำแหล่งเรียนหาหัวข้อถูก 46 จาก 48 ข้อ ไม่มีลิงก์นอกคลังเลย เคสเป็นของสมมุติที่ผู้พัฒนาเขียนเอง จึงยังไม่ใช่ความแม่นยำจริง และเป็นผลของ Typhoon ไม่ใช่ของ Claude ([บันทึกหลักฐาน](evidence/2026-11-06-first-live-typhoon.md); ขั้น 0.3, ADR-021, ADR-022)
- มีโมเดลเปิด (open-weight) ที่ระบบรันเองได้แล้ว (ขั้น 5.8, ADR-026): ปุ่ม *Local open model eval* ใน Actions ให้เครื่องทดสอบของ GitHub สร้างโปรแกรมรันโมเดล (llama.cpp) จากโค้ดรุ่นที่ตรึงไว้ ดาวน์โหลด Typhoon 2.5 รุ่น 4B (สัญญา Apache 2.0) ตรวจลายนิ้วมือไฟล์ แล้วรันชุดข้อสอบเดิมทั้ง 2 ชุด ข้อความไม่ออกไปบริษัท AI ใด ไม่ต้องใช้คีย์ และไม่มีค่าใช้จ่ายเพราะ repo เป็นสาธารณะ แต่เครื่องทดสอบคิดด้วย CPU จึงช้ากว่า Typhoon ออนไลน์มาก ใช้วัดผลได้ แต่ใช้เป็นสมองของหน้าเว็บไม่ได้ (เงื่อนไขของ GitHub) PR ที่แก้ส่วนเชื่อม AI จะได้รอบทดสอบเล็ก 5 เคสอัตโนมัติ รอบเล็กรอบแรก (8 พ.ย.) ตอบได้ทุกข้อและถูกรูปแบบตั้งแต่ครั้งแรก: คัดแยกเคสถูก 5 จาก 5 หาหัวข้อถูก 5 จาก 5 ไม่มีลิงก์นอกคลัง ใช้เวลาราว 2.7–6.5 วินาทีต่อเคสแล้วแต่เครื่อง และรันซ้ำด้วยไฟล์ที่ตรึงแล้วได้ตัวเลขเหมือนเดิมทุกตัว ([บันทึกหลักฐาน](evidence/2026-11-08-first-local-model-smoke.md)) รอบเต็มรอบแรกบน main (8 พ.ย. ราว 66 นาที) ตอบได้ทุกข้อ: เคสที่กฎผิดถูกดันขึ้นคิวด่วนให้คนดูครบ 32 จาก 32 เท่ากับ Typhoon รุ่นใหญ่ผ่าน API คัดแยกเคสถูก 58 จาก 61 (รุ่นใหญ่ 60) หาหัวข้อถูก 44 จาก 48 (รุ่นใหญ่ 46) ไม่มีลิงก์นอกคลัง (0 จาก 142) ช้ากว่ารุ่นใหญ่ราว 7 เท่า และมีคำสั่งแอบแฝง 1 ข้อที่หลอกให้เลือกหัวข้อได้ แต่ลิงก์ยังมาจากคลังเท่านั้น ([บันทึกหลักฐาน](evidence/2026-11-08-first-local-model-full.md)) ยังไม่ใช่ความแม่นยำ ต่อไปเจ้าของโปรเจกต์เลือกทางตามขั้น 5.8: ไม่ผ่าน พอใช้ หรือผ่าน
- หน้าเว็บมีช่อง "อยากเรียน" แล้ว: กดปุ่ม "อยากเรียน" เหนือช่องพิมพ์ พิมพ์เรื่องที่อยากรู้ แล้วกด Enter คำถามส่งทันที (ไม่มีขั้นยืนยันแบบเคส เพราะเป็นแค่คำแนะนำ) คำตอบขึ้นเป็นชั้น: สรุป 1 บรรทัด สิ่งที่ระบบเข้าใจพร้อมถามว่า "เข้าใจถูกไหม" แหล่งที่ควรเริ่มก่อนกับแหล่งที่สำคัญที่สุด แล้วกด "ดูขั้นตอนการเรียน" หรือ "ดูรายละเอียด" เมื่ออยากรู้เพิ่ม เรื่องนอกกรอบบอกตรง ๆ พร้อมรายการ 11 หัวข้อที่ช่วยได้ ถ้าช่อง AI มุมซ้ายล่างขึ้นว่า "AI จำลอง" คำเปรียบใหม่ ๆ อย่าง "บรรณารักษ์ที่รู้ใจ" จะถูกตอบว่านอกกรอบ และหน้าเว็บบอกเหตุผลไว้ เปิด Typhoon ได้ฟรีตามขั้นตอนในแท็บ "ตั้งค่า" (ขั้น 3.4, ADR-023)
- มีด่านความทนทาน (robustness benchmark ขั้นที่ 1) แล้ว: ทุกครั้งที่ส่งโค้ด GitHub ป้อนเคสสุดโหดที่เขียนเอง 270 ข้อ และข้อมูลเปิดที่นักพัฒนาทั่วโลกใช้ (ข้อความแปลก 515 แบบ ไฟล์ทดสอบ JSON 318 ไฟล์ และคำขอจาก CLINC150 กับ BANKING77) เข้าทุกชั้นของระบบ รอบแรกเจอปัญหาร้ายแรง 8 จุด ที่สำคัญที่สุดคือถ้า AI ตอบมี "ตัวอักษรพัง" เคสทั้งเคสจะล้มและไม่ถึงคนตรวจ แก้ครบทั้ง 8 จุดแล้วใน PR #42 (รวมแล้วเมื่อ 8 พ.ย. และเคสที่คุณส่งบนหน้าเว็บจริงหลังรวมยังถึงคนตรวจ): ข้อมูลแปลกได้ "ข้อมูลไม่ถูกต้อง (400)" แทน "เซิร์ฟเวอร์พัง (500)" และเคสที่ AI ตอบมีตัวอักษรพังยังถึงคนตรวจพร้อมความเห็นของ AI 7 จุดแก้นอก Core ส่วนจุดที่ 8 ตรวจตัวอ่าน JSON ของ Core เอง จึงแก้ Core 1 ฟังก์ชันพร้อมบันทึกข้อตัดสินใจ (ADR-025) หลัง E2 ใน PR #64 ผ่าน 239 จาก 270 ข้อ (ก่อน E2 ผ่าน 215 ข้อ; ขั้น 5.4–5.5, [แผนทดสอบ 3 ขั้น](benchmarking.md), [บันทึกหลักฐาน](evidence/2026-11-07-robustness-stage1.md))
- วัดเคสยาก 116 ข้อของด่านความทนทานกับ AI จริง (Typhoon) เป็นครั้งแรกเมื่อ 10 พ.ย.: AI จัดหมวดถูก 104 จาก 116 กฎคำสำคัญถูก 48 จาก 116 เคสภาษาไทย AI ถูก 13 จาก 13 ข้อที่ AI พลาดทั้ง 12 ข้อเฉลยว่า "อื่น ๆ" แต่ AI จับใส่หมวดใกล้เคียง และ AI บอกว่า "มั่นใจสูง" ทุกข้อ ป้ายของชุดนี้ผู้พัฒนาจับคู่เอง จึงยังไม่ใช่ความแม่นยำ ผลนี้เป็นฐานของ[แผนเพิ่มประสิทธิผล](effectiveness_plan.md) ([บันทึกหลักฐาน](evidence/2026-11-10-effectiveness-baseline.md))
- **แก้ตามผู้ตรวจสอบอิสระ (10 พ.ย.) ครบ 4 ข้อ** ([บันทึกหลักฐาน](evidence/2026-11-10-independent-review-response.md)):
  - **คนตัดสินเคสได้แล้ว** (ขั้น 2.2 และ 2.4): เคสที่ "รอคนตรวจ" มีการ์ด "ตัดสินเคสนี้" กด "อนุมัติ" (ใช้หมวดที่กฎเสนอหรือเลือกเอง) หรือ "ไม่อนุมัติ" พร้อมเหตุผล เคสจะเปลี่ยนเป็น "อนุมัติแล้ว" หรือ "ไม่อนุมัติ" ตัดสินแล้วแก้ไม่ได้ กดซ้ำก็ไม่บันทึกซ้ำ และด้านซ้ายมีรายการ "รอรีวิว" ที่เอาเคสด่วนขึ้นก่อน ตอนนี้ผู้ตัดสินคือผู้ถือรหัสเข้าใช้ร่วม คือคุณ (รหัสรายคนอยู่ในขั้น 2.1) ส่วนงานต่อเนื่องหลังอนุมัติ (2.3) ยังไม่ทำ
  - **ด่านปิดข้อมูลส่วนตัวบังคับที่ประตูส่งออกแล้ว**: ตัวกลางเรียก AI (gateway) ปิดข้อมูลซ้ำเองก่อนส่งทุกครั้ง ถ้ายังเจอข้อมูลที่ต้องปิด จะไม่ส่งเลย และโค้ดอื่นสร้างข้อความ "ผ่านการปิดแล้ว" ปลอมเองไม่ได้ ระหว่างทำเจอว่ากฎปิดข้อมูลเดิมปิดซ้ำแล้วได้ผลไม่เหมือนเดิมในบางข้อความ (เช่น "นางสาว" + ชื่อ) จึงแก้เป็นกฎรุ่น 2 (`redact-v2`) คำตอบในชุดข้อสอบทุกชุดเหมือนเดิม
  - **บอกตรง ๆ ว่าเก็บได้นานแค่ไหน**: บนแผนฟรี หน้าเว็บไม่พูดว่า "บันทึกถาวร" แล้ว เตือนก่อนส่งและบนเคสที่รอตัดสิน และถ้าระบบเริ่มใหม่ด้วยที่เก็บว่าง หน้าเว็บจะบอกว่าเคสที่คุณส่งจากเครื่องนี้หายไปกี่รายการ (จำแค่รหัสงาน ไม่จำข้อความเคส) ทางแก้ถาวรยังเป็นแผน Render แบบเสียเงิน (D1)
  - **อีเมลส่วนตัวใน commit**: พบว่ายังเพิ่มขึ้นทุกครั้งที่กด Merge บน github.com (51 commit ตอนเปิดสาธารณะ ตอนนี้ 53) จึงเพิ่มช่องตรวจที่จับอีเมลส่วนตัวใน commit ใหม่ ทางหยุดคือการตั้งค่า 1 อย่างของคุณใน GitHub ส่วนของเก่าคุณเลือกเก็บประวัติไว้ตามเดิมแล้ว (D8 ข้างล่าง)
- เคสแรกหลังระบบตื่นเคยใช้ราว 10 วินาที สาเหตุที่ยืนยันแล้วบนภาพจริงของบริการคือไม่มีไฟล์ที่แปลไว้ล่วงหน้า (bytecode cache) เลย โปรแกรมจึงต้องแปลโค้ดใหม่ทุกครั้งที่เริ่ม แก้แล้วใน PR #60 (งาน E1, 10 พ.ย.): บนเครื่องของ GitHub ที่จำกัดกำลังให้เท่าเครื่องฟรีของ Render เคสแรกเร็วขึ้นจาก 14.4 เป็น 3.1 วินาที ยังไม่ได้วัดบน Render จริง เพราะต้องรวม (merge) ก่อน ([บันทึกหลักฐาน](evidence/2026-11-10-e1-bytecode-cache.md))

- **ทักษะแยกกัน ส่งงานผ่านตัวกลาง (11 พ.ย. ตามที่คุณขอ, ADR-030):** แต่ละทักษะไม่เรียกโค้ดของกัน ส่งงานให้กันผ่านตัวกลาง (exchange) ตามตารางเส้นทางที่มีเลขรุ่น ระหว่างทางมีล่ามขาออกแปลเป็นภาษากลาง และล่ามขาเข้าแปลเป็นภาษาของทักษะปลายทาง เส้นทางแรกใช้งานแล้ว: กด "อนุมัติ" เคส → ระบบสร้างงาน "บันทึกผลหลังอนุมัติ" ทันทีในครั้งเดียวกับการตัดสิน บันทึกว่าเคสไปคิวไหน ใครอนุมัติ พร้อมใบรับจาก Core (นี่คือขั้น 2.3) ข้อความเคสไม่ถูกส่งต่อ ไม่อนุมัติก็ไม่ส่งต่อ ทดสอบกับชุดเคสเดิมทั้ง 3 ชุด 217 เคส ผ่านทุกข้อ และชุดทดสอบเดิมได้ผลเหมือนเดิมทุกข้อ ([แบบและวิธีทดสอบ](skill_handoff.md), [บันทึกหลักฐาน](evidence/2026-11-11-skill-handoff.md)) ยังไม่ได้ลองบน Render เพราะต้องรวมโค้ดก่อน
- **ผู้ช่วยแนะนำแหล่งเรียน: หยุดพัฒนาไว้ก่อน (11 พ.ย. ตามที่คุณสั่ง):** ของเดิมยังใช้ได้และช่องตรวจยังรัน
- **ขีดสุดของระบบ ถ้ามี "ปุ่มอนุมัติเอง" (11 พ.ย. ตามที่คุณขอ, ADR-031):** ผมจำลองปุ่มนี้บนกระดาษจากคำตอบจริงของ Typhoon
  กับข้อสอบกลางจากข้อมูลเปิด (CLINC150, BANKING77, MASSIVE ไทย-อังกฤษ, คำสั่งแอบแฝง BIPIA) ชุดเคสยากที่เขียนใหม่ 128 เคส และชุดเดิม 3 ชุด
  ระบบจริงไม่มีปุ่มนี้ และยังให้คนตัดสินทุกเคส ผลหลัก: ความมั่นใจที่ AI บอกเองใช้แยกถูกผิดไม่ได้ (ในชุดเคสยาก AI บอก "มั่นใจสูง" 122 จาก 128 เคส
  รวมเคสที่ตอบผิด 12 จาก 13 เคส) และไม่มีกติกาไหนในระบบตอนนี้ที่รู้ว่า "เคสนี้ต้องให้คนดู" เคสบัญชีถูกแฮ็ก เรื่องกฎหมาย หรือคำสั่งแอบแฝงจึงหลุดได้
  ([วิธีวัด](autosend_simulation.md), [ผลวัด](evidence/2026-11-11-autosend-limits.md))

**ลำดับต่อจากนี้** แต่ละขั้นจบด้วยสิ่งที่คุณลองเองได้

| ขั้น | ทำอะไร | คุณจะได้ลองอะไร | สถานะ (10 พ.ย. 2026) |
|---|---|---|---|
| 0 | เปิดใช้ออนไลน์บน Render และวัดผล AI จริงครั้งแรก | ใส่เคสบนหน้าเว็บจริง และอ่านผลวัดของ AI จริง | ออนไลน์แล้ว; วัดผล AI จริงครั้งแรกแล้วด้วย Typhoon (0.3, 6 พ.ย.); ที่เหลือรอคุณตัดสินใจ: D1 แผน Render แบบเสียเงิน, D2 API key ของ Claude และ 0.4 กับ Typhoon (ฟรี แต่ข้อความที่พิมพ์บนหน้าเว็บจะถูกส่งไป Typhoon) |
| 1 | เก็บงานเล็ก ๆ ให้ระบบแน่นขึ้น | ยกเลิกเคสที่ยังรอคิวได้ | เสร็จ ยกเว้น 1.4 (สำรองข้อมูล) ที่ต้องใช้แผน Render แบบเสียเงิน |
| 2 | ให้คนรีวิวได้จริง: ผู้รีวิวมีรหัสของตัวเอง กดอนุมัติหรือไม่อนุมัติได้ และ n8n แจ้งเตือน | กล่อง "รอรีวิว" บนหน้าเว็บ และข้อความแจ้งเตือน | เริ่มแล้ว (10 พ.ย. ตามข้อ 4 ของผู้ตรวจสอบอิสระ): 2.2 บันทึกการตัดสินและ 2.4 การ์ดตัดสินกับรายการ "รอรีวิว" ทำแล้ว โดยผู้ตัดสินคือผู้ถือรหัสเข้าใช้ร่วม (คุณ); 2.3 งานต่อเนื่องหลังอนุมัติทำแล้ว (11 พ.ย.) เป็นเส้นทางแรกของตัวกลาง (ขั้น H); 2.1 รหัสรายคน และ 2.5 n8n ยังไม่ทำ |
| 3 | ผู้ช่วยแนะนำแหล่งเรียน (`study_guide.v1`) ตามหลักปรัชญาของคุณ | พิมพ์เรื่องที่อยากรู้ด้วยคำธรรมดา แล้วได้แหล่งเรียนไม่เกิน 5 แหล่งพร้อมลำดับการเรียน | สร้างครบทุกขั้นแล้ว (คุณเลือกขั้นนี้ก่อนขั้น 2 เมื่อ 5 พ.ย.): 3.1 คลังแหล่งเรียน 3.2 ตัวผู้ช่วย และ 3.3 ชุดข้อสอบ ทำแล้ว (ดูตัวอย่างคำตอบและผลข้อสอบใน Actions ได้); 3.4 ช่อง "อยากเรียน" บนหน้าเว็บ สร้างและ merge แล้ว (7 พ.ย.) คุณลองบนหน้าเว็บจริงผ่านแล้ว (8 พ.ย.); รันกับ AI จริง (Typhoon) แล้ว หาหัวข้อถูก 46 จาก 48 ข้อ ไม่มีลิงก์นอกคลัง (Claude รอ D2); **หยุดพัฒนาเพิ่มไว้ก่อนตามที่คุณสั่ง (11 พ.ย.)**: ของที่มีอยู่ยังใช้ได้และช่องตรวจยังรันเหมือนเดิม |
| 4 | ช่องคุยภาษาธรรมดา: ระบบเข้าใจว่าคุณขออะไร บอกตรง ๆ เมื่อเรื่องอยู่นอกกรอบ และถามกลับ 1 คำถามเมื่อข้อมูลไม่พอ | คุยกับระบบได้เลย ไม่ต้องเลือกประเภทงานเอง | ยังไม่เริ่ม (ขั้น 3 สร้างครบแล้ว เริ่มได้เมื่อคุณเลือก) |
| 5 | ติดตามเส้นทางของแต่ละงาน (เวลา token จุดที่ช้า) ด่านตรวจผลรายเคส และแผนทดสอบ 3 ขั้นด้วยข้อมูลเปิด | ตัวเลขคิวและเวลาบนหน้าเว็บ ช่องตรวจบน PR แล้วต่อด้วยเส้นทางงานใน Honeycomb; ผลด่านความทนทานในหน้าสรุปของ *Core logic tests* | เสร็จแล้วทั้ง 5.1, 5.2, 5.3 และ 5.4; เส้นทางงานแรกเข้า Honeycomb เมื่อ 4 พ.ย. 00:23 น.; ด่านความทนทาน (5.4) รวมเข้า main แล้ว 7 พ.ย.; แก้ 8 bug ที่เจอแล้ว (5.5, PR #42 รวมแล้วเมื่อ 8 พ.ย.); E2 ใน PR #64 แก้จุดอ่อนของกฎได้ 24 จุด เหลือจุดอ่อนทั้งหมด 20 จุด ขั้นข้อสอบกลาง (5.6) สร้างและวัดกับ Typhoon แล้ว 11 พ.ย. พร้อมการจำลองปุ่มอนุมัติเอง (5.9) และวัดคำสั่งแอบแฝงครั้งแรก (ส่วนหนึ่งของ 5.7); ส่วนที่เหลือของ 5.7 ยังไม่ทำ; 5.8 โมเดลเปิดที่รันเองบนเครื่องทดสอบของ GitHub สร้างแล้วใน PR #46 และรันเต็มรอบแรกแล้ว 8 พ.ย. (ดันเคสที่กฎผิดขึ้นคิวด่วนครบ 32/32) รอเจ้าของโปรเจกต์เลือกทาง |
| 6 | AI วางแผนงานหลายขั้น ระบบตรวจแผนก่อนรัน และเครื่องมืออื่นเรียกใช้ผ่าน MCP ได้ | สั่งงานจากแอป Claude ได้ | ยังไม่เริ่ม (ต้องรอขั้น 2–4) |
| 7 | เตรียมพร้อมก่อนให้คนอื่นใช้ หรือก่อนเปิด repo สาธารณะ | รายงานตรวจความปลอดภัย และรายการตรวจก่อนเปิดตัว | เริ่มแล้ว: 7.1 ปิดข้อมูลส่วนตัวก่อนส่งให้ AI ทำแล้ว และตั้งแต่ 10 พ.ย. ตัวกลางเรียก AI บังคับปิดซ้ำเองก่อนส่ง ส่วนการจำกัดว่าใครเห็นคีย์ AI ได้ เขียนแผนไว้ ยังไม่ทำ; 7.4 เสร็จ: repo นี้เป็นสาธารณะพร้อมประวัติทั้งหมดตั้งแต่ 8 พ.ย. (D5) เปลี่ยนคีย์ Sentry แล้ว และเปิดระบบสแกนคีย์ของ GitHub แล้ว; มีผู้ตรวจสอบอิสระอ่านโค้ดครั้งแรกเมื่อ 10 พ.ย. ตอบครบ 4 ข้อแล้ว และคุณเลือกเก็บประวัติอีเมลเก่าไว้ตามเดิม (D8) |
| E | [แผนเพิ่มประสิทธิผล](effectiveness_plan.md) 6 งาน (E1–E6): เคสแรกหลังระบบตื่นเร็วขึ้น กฎรุ่น 2 ที่อ่านภาษาไทยได้ หน้าเว็บจริงใช้ AI จริง เก็บคำตอบ "เข้าใจถูกไหม" ให้ AI แยก "อื่น ๆ" ได้ดีขึ้น และคลังแหล่งเรียนที่มีภาษาไทยมากขึ้น | เวลาของเคสแรก ข้อเสนอหลักของเคสภาษาไทย และตัวนับ "เข้าใจถูก" บนหน้าเว็บ | เขียนแผนแล้วเมื่อ 10 พ.ย. ตามที่คุณขอ (PR #50); E1 สร้างแล้วใน PR #60 (10 พ.ย.): ภาพของบริการมีไฟล์ที่แปลไว้ล่วงหน้าครบแล้ว บนเครื่องของ GitHub ที่จำกัดกำลังให้เท่าเครื่องฟรี เคสแรกเร็วขึ้นจาก 14.4 เป็น 3.1 วินาที รวมแล้วเมื่อ 10 พ.ย. ยังรอวัดบน Render จริง; E2 สร้างและวัดครบใน PR #64: กฎถูก 61/61 ในชุดพัฒนา 105/116 ในชุดเคสยาก และ 22/40 ในชุดที่กันไว้ ([ผลวัดและข้อจำกัด](evidence/2026-11-11-e2-rules-v2.md)); E3 รอคุณตัดสินใจ; E4 และ E6 (ของผู้ช่วยแนะนำแหล่งเรียน) หยุดไว้ก่อนตามที่คุณสั่ง (11 พ.ย.) |
| H | [ทักษะแยกกัน ส่งงานผ่านตัวกลาง](skill_handoff.md) มีล่ามแปลเป็นภาษาของทักษะปลายทางระหว่างทาง (H1–H5) | ตอนนี้: หน้าสรุปของ *Core logic tests* บน PR; หลังรวม: อนุมัติเคสบนหน้าเว็บแล้วเห็นงานที่ส่งต่อมา 1 งาน และกล่อง "ส่งต่อแล้ว" | สร้างแล้วตามที่คุณขอ (11 พ.ย., H1–H3): เส้นทางแรก "อนุมัติเคส → บันทึกผลหลังอนุมัติ" ทำงานแล้ว หน้าเว็บแสดงการส่งต่อทั้งสองทาง ทดสอบกับเคสเดิม 217 เคสผ่านทุกข้อ; รอรวมโค้ดแล้วลองบนหน้าเว็บจริง; ทักษะใหม่ตัวแรก (H4) รอคุณเลือก |

**เรื่องที่คุณต้องตัดสินใจเอง** อยู่ในตาราง [Owner decisions](#owner-decisions) ข้างล่าง เช่น
- จะจ่ายค่า Render เพื่อให้เคสไม่หายหรือไม่
- จะใส่ Claude API key หรือไม่ (ไม่ใส่ก็วัดผลกับ AI จริงได้ผ่าน Typhoon)
- โมเดลเปิดที่รันเองบนเครื่องทดสอบของ GitHub ผ่าน พอใช้ หรือไม่ผ่าน หลังรอบเต็มรอบแรก (ขั้น 5.8)
- ใครเป็นผู้รีวิว
- จะเปิด repo เป็นสาธารณะเมื่อไร
- จะให้หน้าเว็บจริงใช้ AI จริง (Typhoon ฟรี) หรือไม่ และจะเริ่มงานไหนของแผนเพิ่มประสิทธิผลก่อน (E1–E6)
- ทักษะใหม่ตัวแรกที่จะต่อกับตัวกลาง (H4) คืออะไร
- จะมี "ปุ่มอนุมัติเอง" จริงหรือไม่ (D9): ตอนนี้ยังไม่ควร เพราะผลวัด (5.9) บอกว่าความมั่นใจของ AI ใช้แยกถูกผิดไม่ได้ และการเปลี่ยนนี้แก้กติกาข้อ 4

## How to use this file (for Claude Code)

1. **Pick the next item.** Work from the top. Take the first item that is not ✅ and whose **Needs** are
   met. Items marked **owner** need clicks or a decision from the owner, so prepare everything first, then
   give them the steps in Thai.
2. **One work package ≈ one PR.** Split big packages. Never mix two packages in one PR.
3. **When a package is done:**
   - tick it in the status table;
   - update architecture.md (§5–§10 as relevant), the feature doc and the README;
   - add a dated evidence note if you measured anything (see [Evidence track](#evidence-track)).
4. **When reality differs from this plan** (a tool changed, or the owner decided something), update this
   file in the same PR and say so in the PR description. The plan serves the work. If the owner wants them,
   packages can be mirrored as GitHub or Linear issues, but this file stays the source of truth.
5. **How each package is written.** It has some or all of these parts:
   - **Goal** and **Why**;
   - **Tasks**;
   - **Done when** (automated tests, unless it says otherwise);
   - **Owner test** (in Thai);
   - **Don't**.

## Status at a glance

Done before this plan: A (v1 rules), A2 (AI gateway, shadow mode, scorecard, Sentry), B (intake API, queue,
Runner, web page), the docs refresh and the Claude Code session hook.

Marks: ✅ done · 🟡 built or partly checked (the status says what is left) · ⬜ not started · ⏸ paused by the
owner.

| ID | Work package | Status | Needs |
|---|---|---|---|
| 0.1 | Put round 2 online on Render | ✅ live since 2026-11-01; graceful stops confirmed on Render ([evidence note](evidence/2026-11-03-render-operations.md)) | — |
| 0.2 | Free or paid hosting | ⬜ owner decision D1 | 0.1 |
| 0.3 | First scorecard run with a real model | ✅ path A, Typhoon (ADR-021, ADR-022; PR #37, #38): the first run got 0/5 answers (Typhoon ignores `response_format`), fixed; on the full sets triage AI correct 60/61 in two runs and study guide topic correct 46/48 ([evidence note](evidence/2026-11-06-first-live-typhoon.md)). Path B, Claude, still needs D2 | — |
| 0.4 | Claude for the online page | ⬜ optional | 0.1, 0.3 |
| 0.5 | Skip Render deploys for docs-only commits | ✅ PR #15; merges #19, #20 and #24 did not deploy, code merges did ([evidence note](evidence/2026-11-03-render-operations.md)) | 0.1 |
| 0.6 | Open Dependabot PRs #1–#5 | ✅ #1–#5 closed (they edit files removed in PR #6); PR #20 moved the workflows to the Node 24 action versions, and CI no longer warns about Node.js 20 | — |
| 1.1 | Neutral telemetry phase names (the one planned Core change) | ✅ PR #21 | — |
| 1.2 | Request ids to follow a request through the logs | ✅ PR #22 | — |
| 1.3 | Cancel a job that is still queued | ✅ PR #23 | — |
| 1.4 | Backup, restore and retention | ⬜ | D1 = paid (disk) |
| 1.5 | Docs truth checks in CI | ✅ PR #24 | — |
| 1.6 | New look for the web page from the owner's mockup: chat intake with a confirm step, Flow and Trace, read-only settings | ✅ PR #18, merged and deployed 2026-11-03; the owner reported the owner test passed on the live page | — |
| 2.1 | Personal access tokens and roles (replaces the shared key) | ⬜ | — |
| 2.2 | Review ledger and decisions API | 🟡 built on 2026-11-10 before 2.1 (ADR-027): the owner's shared key is the reviewer's credential; per-role denial waits for 2.1 | 2.1 for per-person identity |
| 2.3 | Linked phase-B job on approval | 🟡 built on 2026-11-11 as the first route of the skill-handoff exchange (H3, ADR-030): one approval starts exactly one `case_triage.v2.apply` job with a Core receipt ([evidence](evidence/2026-11-11-skill-handoff.md)); the owner test on the live page after the merge is left | 2.2 |
| 2.4 | Reviewer inbox on the web page | 🟡 built on 2026-11-10: a decision card on every waiting case and a "รอรีวิว" list, elevated first; the owner test after the merge is left | 2.2 |
| 2.5 | n8n intake and reviewer notifications | ⬜ | 2.1, 2.2, D3 |
| 2.6 | Side-effect contract | ⬜ when needed | before any outward action |
| 2.7 | Artifact store with hash checks | ⬜ when needed | — |
| 2.8 | Measure rules vs AI against reviewer labels | ⬜ | 2.2, 0.3 |
| 3.1 | Topic catalog and verified resource library | ✅ PR #32; links checked by *Study library link check* on the PR ([evidence note](evidence/2026-11-05-study-library-links.md)); the weekly run starts after the merge | — |
| 3.2 | `study_guide.v1` workflow | ✅ PR #33; first live run with Typhoon in PR #38 (topic correct 46/48, 0 of 142 links outside the library); Claude needs D2 | 3.1 |
| 3.3 | Study-guide evaluation set and scorecard | ✅ PR #34 with the mock in CI (an eval gate); first live run with Typhoon on 2026-11-06 (PR #38): topic correct 46/48, 0 of 142 links outside the library; Claude after D2 | 3.2 |
| 3.4 | Study guide on the web page | ✅ PR #39 (2026-11-07): a case / study switch above the box, a layered answer, questions sent without a confirm card (ADR-023); the owner's test on the live page passed on 2026-11-08 (mock AI) | 3.2 |
| 4.1 | The frame: a versioned catalog of what the system can do | ⬜ | 3.2 |
| 4.2 | `intake.route.v1`: the plain-language router | ⬜ | 4.1 |
| 4.3 | Layered answers (summary → steps → details) | ⬜ | 4.2 |
| 4.4 | Chat-style page | ⬜ | 4.2 |
| 5.1 | OpenTelemetry tracing to Honeycomb | ✅ PR #30; the first trace seen in Honeycomb on 2026-11-03 ([evidence note](evidence/2026-11-03-first-trace-honeycomb.md)), and the gap it found (steps' agent versions) fixed after it | 1.1, 1.2 |
| 5.2 | Evaluation gate in CI | ✅ PR #27 | — |
| 5.3 | Queue and run-time metrics on the status page | ✅ PR #26 | — |
| 5.4 | Robustness benchmark, stage 1: open and synthetic edge cases as a CI gate | ✅ PR #41 (2026-11-07), merged after the owner checked the run page; first run: 206/270 own items pass, 8 bugs, 0 of 4,680 sweep checks broke a promise ([evidence note](evidence/2026-11-07-robustness-stage1.md)) | — |
| 5.5 | Fix what stage 1 found (the 8 bugs, then the gaps) | 🟡 the 8 bugs fixed in PR #42, merged 2026-11-08 (after the deploy the owner's case on the live page still reached review): 239/270 own items pass after E2 (215 after PR #42), 0 bugs, 20 gaps; one small Core change (ADR-025); E2 in PR #64 fixes 24 of the 27 original rules gaps and records the three retained limits ([evidence](evidence/2026-11-11-e2-rules-v2.md)); the other gap decisions remain open | 5.4 |
| 5.6 | Stage 2: open benchmarks (CLINC150, BANKING77, MASSIVE th-TH/en-US) with Typhoon | ✅ built in PR #66 (2026-11-11): the sets are built at run time from pinned sources (`tests/open_benchmarks/`, SHA-256 checked, nothing downloaded committed), the mock run is a PR check of *Auto-approve limits*, and the first Typhoon run is in the [evidence note](evidence/2026-11-11-autosend-limits.md); the study guide's part waits while it is paused | 5.4 |
| 5.7 | Stage 3: prompt injection, personal data, load and restarts, weekly live drift | 🟡 the first injection measurement in PR #66 (BIPIA's 75 attacks and 16 steering or approval attempts, [evidence](evidence/2026-11-11-autosend-limits.md)); personal data, load, restarts and drift not built | 5.4; drift schedule is the owner's choice |
| 5.9 | Auto-approve limits: a simulated "send it myself" button on the open benchmarks and a hard set (ADR-031, [design](autosend_simulation.md)) | ✅ PR #66 (2026-11-11), asked for by the owner: a replay of saved answers, never wired into the service; on the 128-case hard set Typhoon said `high` on 122 and was wrong on 13, 12 of them `high`; every policy lets cases that must see a person through ([evidence](evidence/2026-11-11-autosend-limits.md)) | 5.6 |
| 5.8 | Local open-model lane: llama.cpp and Typhoon 2.5 4B on the GitHub runner (ADR-026) | ✅ built in PR #46, with two smoke runs ([evidence note](evidence/2026-11-08-first-local-model-smoke.md)); first full run on `main` on 2026-11-08: rule mistakes raised 32/32 (Typhoon 32/32), triage AI correct 58/61 (Typhoon 60/61), topic correct 44/48 (Typhoon 46/48), 0 of 142 links outside the library, about 7 times Typhoon's latency ([evidence note](evidence/2026-11-08-first-local-model-full.md)); next, the owner chooses a branch (5.8, "After the first full run", step 2) | — |
| 6.1 | Pattern A: bounded read-only tool loop | ⬜ | 3.2 |
| 6.2 | Pattern B: planner → checked plan → linked job | ⬜ | 2.2, 4.2 |
| 6.3 | MCP server (submit, get, list; never review decisions) | ⬜ | 2.1 |
| 7.1 | Mask personal data before AI calls; narrow key exposure | 🟡 masking built in PR #28, enforced by the gateway itself since 2026-11-10 (`redact-v2`, ADR-028); key exposure: design note only | before any real data |
| 7.2 | Production HTTP server and authentication hardening | ⬜ | before other users |
| 7.3 | Independent security review | ⬜ owner; a first independent review of the code and docs on 2026-11-10 found four problems, all answered ([evidence](evidence/2026-11-10-independent-review-response.md)); the threat model and a test of the running service are left | 7.1, 7.2 |
| 7.4 | Public-release checklist | ✅ public since 2026-11-08 with its full history (D5): history audited, the 7 run logs that could print the old DSN deleted, read-only workflow tokens, README section for visitors and SECURITY.md (PR #44); the owner replaced the Sentry DSN, deleted the merged branches, switched the visibility and turned on secret scanning, push protection and private vulnerability reporting | — |
| 7.5 | Consented pilot with real volunteers | ⬜ owner decision D4 | 7.1–7.3 |
| 7.6 | The personal e-mail address in the public history | ✅ new commits checked in CI (2026-11-10); D8 decided the same day: the history stays as it is | — |
| E1 | First case after a start: seconds, not ten ([effectiveness plan](effectiveness_plan.md)) | 🟡 built in PR #60 (2026-11-10): the image had no bytecode cache (0 of the 141 modules the Runner imports) and now carries one, required by *Service container*; in CI the first case went from 0.989 s to 0.256 s, and from 14.4 s to 3.1 s with the container held to 0.1 CPU ([evidence note](evidence/2026-11-10-e1-bytecode-cache.md)); on Render it was 9.0 to 10.5 s before, and the time after is measured once the PR is merged | — |
| E2 | Rules v2: an official suggestion that reads Thai (also decides the 27 rules gaps of 5.5) | ✅ built and measured in PR #64, merged on 2026-11-11: rules 61/61 development (Thai 26/26), 105/116 edge, 22/40 held-out; Typhoon answered all 217 cases, no v1-correct case regressed, code checks passed; 24 original rules gaps fixed, 3 retained. Fewer elevated flags leave 8 jointly wrong edge cases unflagged as before (E5 open). [Evidence and same-answer comparison](evidence/2026-11-11-e2-rules-v2.md) | — |
| E3 | A real model behind the online page | ⬜ owner decision (0.4, D7); today the page's mock finds the study topic for 2/48 | 0.1 |
| E4 | Record the answer to "เข้าใจถูกไหม" | ⏸ paused with the study guide (owner, 2026-11-11); planned | the owner resumes it; an ADR |
| E5 | The edge of `other`, and a confidence that means something | ⬜ planned; 5.6 is built, and its first run confirms the problem on text nobody here wrote: most of Typhoon's mistakes are `other` requests pulled into a near category, nearly all with `high` confidence ([evidence](evidence/2026-11-11-autosend-limits.md)) | the owner labels about 20 borderline requests |
| E6 | A study library that serves Thai readers | ⏸ paused with the study guide (owner, 2026-11-11); planned; today 1 of 17 resources is in Thai | the owner resumes it; the owner reads each candidate |
| H1 | Skill handoff: the design and ADR-030 ([skill_handoff.md](skill_handoff.md)) | ✅ 2026-11-11; the owner asked for it to be built and shown working | — |
| H2 | The common language and the first translators | ✅ built 2026-11-11: `app/exchange/`, `vocabulary-v1`, `out.case_triage.v2@1`, `in.case_triage.v2.apply@1`, isolation and golden-output tests | H1 |
| H3 | The exchange and the first route (2.3's linked job after an approval) | 🟡 built 2026-11-11: route table, queue schema 3 with the `handoffs` ledger, the handoff inside the decision's transaction, API fields; new suite and all 217 existing triage cases pass ([evidence](evidence/2026-11-11-skill-handoff.md)); the owner test on the live page after the merge is left | H2, 2.2 |
| H4 | The first new skill, joined only through translators | ⬜ | H3, the owner's choice |
| H5 | The chain on the page and in traces | 🟡 the page shows the chain both ways (2026-11-11); the trace link is not built | H3 |

Phase 2 can be built and tested without a disk. Real use needs D1 = paid: on the free plan, tokens and
decisions would vanish on every sleep. Since 2026-11-10 the API and the page say so at every write (ADR-029).

---

## Phase 0 — Go live, and measure the real AI once

### 0.1 Put round 2 online on Render (owner + Claude)

- **Goal:** the owner opens a public link, enters the access key and submits cases.
- **Why:** Milestone B is built but has only run in CI. The owner tests by using it.
- **Tasks:**
  1. **Check what already exists.** PR #11 is merged, so the owner may already have created the service.
     Look with the Render connector (`list_services`) if it is available; otherwise ask once.
  2. **If there is no service yet,** give the owner the Thai steps in [intake_queue.md](intake_queue.md)
     ("สิ่งที่ต้องทำเพื่อเปิดใช้บน Render"):
     sign in with GitHub → New → Blueprint → this repo → Deploy Blueprint → copy `NEURON_FLOW_ACCESS_KEY`
     from the Environment tab.
  3. **After the first deploy:**
     - check that `GET /healthz` returns `{"ok": true, "access_key": "configured"}`;
     - read the deploy and app logs (`list_deploys`, `list_logs`, `list_events`);
     - fix anything that fails.
- **Done when** (checked by hand and recorded in the PR or chat):
  - the deploy is Live and `/healthz` reports the key as configured;
  - the example cases on the page reach "รอคนรีวิว" (`REVIEW_REQUIRED`);
  - pressing "ส่งซ้ำ" returns the same job;
  - `/v1/status` shows the Runner as alive.
- **Owner test (ไทย):**
  1. เปิดลิงก์ `https://neuron-flow….onrender.com` แล้วใส่รหัสเข้าใช้
  2. กดเคสตัวอย่าง ทุกเคสต้องขึ้น "รอคนรีวิว"
  3. กด "ส่งซ้ำ" ต้องได้เลขงานเดิม
  4. ทิ้งไว้ 20 นาทีแล้วเปิดใหม่ หน้าเว็บจะรอประมาณ 1 นาที และเคสเก่าจะหายตามที่ป้ายเตือนไว้ (แผนฟรี)
- **Don't:** paste the access key into chat, issues, docs or commits, or change the plan in the dashboard.
- **Status (2026-11-01, read through the Render connector):**
  - The owner created `neuron-flow` from the Blueprint. The first deploy (commit `8695ad0`) is Live at
    https://neuron-flow.onrender.com, and Render's `/healthz` checks return 200.
  - The logs show the Runner starting with the mock AI, the page polling `/v1/status`, and one case going
    from `POST /v1/jobs 202` to `REVIEW_REQUIRED`.
  - The owner's resend check passed. After the PR #15 deploy, the logs show `POST /v1/jobs 200` at 15:10:04,
    15:10:22 and 15:10:50 UTC. A 200 reply to `POST /v1/jobs` is only ever a duplicate returning the existing
    job (`app/api/routes.py`); a new job gets 202.
  - Found while checking: replacing the old instance logged `[FATAL tini (1)] Unexpected error when
    forwarding signal: 'Operation not permitted'`, with no `serve: stopping` after it. Root in Render's
    containers lacks `CAP_KILL`, so a root tini could not pass SIGTERM on to the service, which runs as
    `neuron`. Every stop killed the service instead. This was reproduced in CI with `--cap-drop KILL` and
    the real tini. It was fixed by running tini as `neuron` (`app/boot.py`, PR #16); the CI job now keeps
    `--cap-drop KILL`.
  - **Confirmed on Render** ([evidence note](evidence/2026-11-03-render-operations.md)): the fixed image's
    first free-plan sleep (2026-11-01 15:43:45 UTC) and the deploy replacements on 2026-11-03 logged
    `serve: stopping (signal 15)` and `runner: stopping after the current job`, with no FATAL line. The
    same note records the free-plan sleep (about 15 minutes after the last request) and the cold start
    (first job 9–10 s, later jobs 0.1–0.4 s).

### 0.2 Free or paid hosting (owner decision D1)

- **Goal:** decide whether cases must survive restarts.
- **Facts** (check current prices before quoting them):
  - **Free:** $0. It sleeps after 15 idle minutes, has no disk, and loses the queue on every sleep, restart
    and deploy.
  - **Paid:** the `0.5c-512mb` instance (about $7 a month) plus a 1 GB disk (about $0.25 a month).
- **Tasks if paid:**
  1. In `render.yaml`, set `plan: 0.5c-512mb`, uncomment the `disk` block (mount path `/var/data`) and set
     `NEURON_FLOW_DATA_DIR=/var/data`.
  2. Open a PR.
  3. After the merge, check that a case survives a manual redeploy.
- **Done when:** a case submitted before a redeploy is still there after it (checked by hand), and the
  page's storage label shows persistent storage.
- **Owner test (ไทย):**
  1. ส่งเคส 1 เคส
  2. ใน Render กด Manual Deploy
  3. เปิดหน้าเว็บใหม่ เคสเดิมต้องยังอยู่

### 0.3 First scorecard run with a real model

- **Goal:** the first honest measurement of a real model, failures included (funding evidence gate 2).
- **Two paths.** On 2026-11-06 the owner's Anthropic account asked for card verification, which the owner
  could not do, so a free path was added first. Both use the same gateway, validators and scorecards, and
  each result names its provider and model.
  - **A. Typhoon (free, no card; done, ADR-021, ADR-022).** SCB 10X's Thai-first model, through its free
    research API (about 200 requests a minute). The key is the repository secret `TYPHOON_API_KEY` (set by the
    owner on 2026-11-06). The first free path, GitHub Models (ADR-020), turned out to be retired since
    2026-07-30.
  - **B. Claude (needs D2).** An API key from the Claude Console with a monthly spend limit, stored as the
    repository secret `ANTHROPIC_API_KEY`.
- **Tasks:**
  1. **Owner, path A:** run *Actions → Shadow eval with Typhoon (manual)* with the default model
     (`typhoon-v2.5-30b-a3b-instruct`) and `limit` 5, then again on all 61 cases; then *Study guide eval with Typhoon
     (manual)* the same way.
  2. **Owner, path B (after D2):** create the key, set the spend limit, add the secret, then run *Actions →
     Shadow eval with Claude (manual)* with `claude-haiku-5-5` and `limit` 5, then all 61 cases.
  3. Record each result in `docs/evidence/<date>-first-live-<provider>.md`:
     - the commit SHA, the run link, the model and the served model;
     - every rate as numerator/denominator;
     - the unavailable and failed counts, token totals and latency;
     - the cases both rules and AI got wrong.

     Compare with the mock run using `--compare-with`.
  4. Update every place that still says Claude has never been run: architecture.md (A2), the Limits of
     case_triage_v2_shadow.md, the README's Scope and limits, and the next evidence gates in
     funding/README.md.
- **Done when:** the evidence note exists, with denominators and failures, and no doc still says
  "never run".
- **Status (2026-11-06): path A done** ([evidence note](evidence/2026-11-06-first-live-typhoon.md)).
  - Run 1 (the owner's, `main`): HTTP 200 but plain `key: value` lines, so the AI answered 0/5
    (`unavailable: invalid_model_output` 5). Typhoon ignores `response_format`. ADR-022 (PR #38): the client
    also states the answer format in words, reads the one JSON object, and puts the format version in the
    agent version.
  - Then on PR #38's branch, all 61 triage cases twice and all 67 study requests once: triage AI correct
    60/61 in both runs (rules 29/61; Thai 26/26), with the 32 rule mistakes all raised and no case wrong
    for both; study guide topic correct 46/48, out of scope precision 16/17 and recall 16/19, 0 of 142
    links outside the library, 0 of 67 answers over five. No AI step ended unavailable or failed.
  - Developer-labelled synthetic cases and a few runs: a first measurement of Typhoon, not accuracy, and
    nothing about Claude. The comparison with the mock is by rates on the run pages; this session cannot
    download the per-case reports.
- **Owner test (ไทย):**
  1. เปิด GitHub → Actions → *Shadow eval with Typhoon (manual)* → Run workflow
  2. ช่อง model ไม่ต้องแก้ ช่อง limit ใส่ 5 แล้วกด Run workflow
  3. รอราว 1 นาทีจนเป็นสีเขียว แล้วกดเข้าไปดู Summary: หัวข้อ "ตรวจการเชื่อมต่อ AI" ต้องขึ้น "answered" และมีตารางคะแนน
     กับหมายเหตุว่าใช้ Typhoon (ไม่ใช่ Claude)
  4. ถ้าผลดูปกติ รันอีกรอบโดยปล่อยช่อง limit ว่าง (ครบ 61 เคส ใช้เวลาราว 2 นาที)
  5. (เมื่อมี Claude API key แล้ว, D2) ทำแบบเดียวกันที่ *Shadow eval with Claude (manual)*
- **Don't:**
  - set a target before the first run;
  - present a Typhoon result as a Claude result, or compare them without naming both models;
  - rerun to hide a bad result;
  - convert tokens to money (prices change);
  - treat developer-labelled synthetic cases as ground truth.

### 0.4 Claude for the online page (optional)

- **Tasks:**
  1. **Owner:** add `NEURON_FLOW_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` in Render's Environment
     tab. Never put them in `render.yaml`.
  2. Check that `/v1/status` shows the Claude mode.
  3. Submit three cases and check that the AI's second opinion and reason appear.
  4. Check Sentry for warnings.
- **Cost:** each case makes one short Claude request.
- **Why it matters (2026-11-10):** the page's mock finds the study topic for 2/48 requests where Typhoon
  found 46/48, and on the hard triage set it raises 26 of the rules' 68 mistakes where Typhoon raised 60.
  This is package E3 of the [effectiveness plan](effectiveness_plan.md).
- **Free option (added 2026-11-07, with 3.4):** Typhoon instead of Claude (ADR-021). The owner adds
  `NEURON_FLOW_LLM_PROVIDER=typhoon` and `TYPHOON_API_KEY` as new rows in the Environment tab, then the
  same checks. Case triage and the study guide then both use it; a study question makes one or two calls.
  Typhoon collects usage data, so synthetic data only. The settings tab of the page lists these steps, and
  how to go back to the mock.
- **Changing the model or prompt later** is a new agent version. Jobs caught mid-way then fail as
  `configuration_changed`, by design.

### 0.5 Skip Render deploys for docs-only commits

- **Why:** every merge to `main` redeploys. On the free plan a deploy wipes the queue, even when only the
  docs changed.
- **Tasks:**
  1. Check Render's current Blueprint docs for build filters (`buildFilter` with `paths` or
     `ignoredPaths`) on Docker web services.
  2. If they are supported, ignore `docs/**`, `**/*.md` and `.claude/**`. Keep `render.yaml`, the
     `Dockerfile` and the code included.
  3. The *Service container* job validates the file against Render's schema.
- **Done when:** a docs-only merge shows as skipped in Render's events, and a code merge still deploys.
- **Status (2026-11-01):** built. `render.yaml` sets `buildFilter.ignoredPaths` to `*.md`, `**/*.md`,
  `docs/**`, `tests/**`, `examples/**`, `.github/**` and `.claude/**`. None of these changes the running
  service: `.dockerignore` keeps them out of the image, except `README.md`, which the `Dockerfile` copies
  but nothing reads. Tests, demos and CI are skipped as well as the docs, for the same reason.
  - `.github/scripts/check_render_blueprint.py` (the *Service container* job) fails if any tracked file
    under `app/`, `neuron_flow/`, or the `Dockerfile`, `.dockerignore` or `LICENSE` would be ignored. It
    also fails if a docs, test or CI example would still deploy, or if Render's schema stops listing
    `buildFilter.ignoredPaths`.
  - Render's docs could not be read from the session (the network blocks `render.com`), so the field
    names rest on Render's published schema, which CI applies.
  - **Confirmed (2026-11-03, [evidence note](evidence/2026-11-03-render-operations.md)):** Render has no
    deploy for the docs or CI-only merges #19, #20 and #24, and every merge that changed code (#16, #18,
    #21–#23) deployed. Render lists no `commit_ignored` events, so the evidence is the missing deploys.

### 0.6 Open Dependabot PRs #1–#5

- **#1–#4** bump `actions/download-artifact`, `actions/upload-artifact`, `actions/setup-python` and
  `actions/checkout` to new major versions:
  - read each changelog for breaking changes;
  - rebase each PR and let CI run;
  - merge them one at a time, only with the owner's OK.
- **#5** bumps `tomli` in `requirements-build.txt`, a file that no longer exists on `main`. Close it with a
  comment.
- **Status (2026-11-03): the plan above did not fit, so it changed.**
  - All five PRs (opened 2026-10-30) edit files that PR #6 removed: `ci.yml`, `release.yml`,
    `approved-publication.yml` and `requirements-build.txt`. There is no `.github/dependabot.yml` any
    more, so Dependabot cannot rebase them onto today's workflows. They were closed with a comment.
  - The real need was still there: CI warned that `actions/checkout@v4`, `actions/setup-python@v5` and
    `actions/upload-artifact@v4` target the deprecated Node.js 20 and are forced onto Node.js 24.
  - PR #20 moves all four current workflows to `checkout@v7`, `setup-python@v7` and
    `upload-artifact@v7`. From the release notes, the breaking changes are: the Node 24 runtime (runner
    2.327.1 or newer; GitHub-hosted runners qualify); checkout's safer defaults for `pull_request_target`
    and `workflow_run` (not used here); setup-python v7 removed the `pip-install` input (not used here);
    upload-artifact v7 adds optional unzipped uploads (the default is unchanged). `download-artifact` is
    no longer used, so #1 had nothing to replace.
  - **Confirmed after the merge:** CI on `main` no longer warns that actions target Node.js 20. The only
    notice left is GitHub's own: the `ubuntu-latest` label is moving to Ubuntu 26, and CI is green on it.
  - Not done, on purpose: a new `.github/dependabot.yml`. It would bring a PR for every new action
    version; whether to turn that on is the owner's choice.

---

## Phase 1 — Small hardening (P1)

### 1.1 Neutral telemetry phase names (the one planned Core change)

- **Where:** around line 308 of `neuron_flow/engine.py`. It still maps the legacy agent names
  `csv_validate`, `csv_calculate` and `csv_verify` to phases; every other agent is recorded as `agent`.
- **Tasks:**
  1. Record the step id as the phase, and remove the mapping. Step ids already match `NAME` in
     `neuron_flow/model.py` (`^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$`), which also passes `Telemetry.record`'s
     check.
  2. Update the tests that assert phase names.
  3. Update architecture.md §3, and every "Core unchanged since `09100f7`" sentence, to say Core changed
     once, for this fix, with the commit.
- **Done when:**
  - a job's telemetry shows its own step ids;
  - no `csv_` string remains in Core;
  - all tests pass;
  - the PR changes nothing else in Core.
- **Don't:** add fields to `AgentDefinition` or change job fingerprints for this.

### 1.2 Request ids

- **Goal:** follow one request from the access log to the job record.
- **Constraint:** the logging privacy rules in intake_queue.md stay as they are. Access lines carry no case
  text, no query strings, no job ids, and never the key.
- **Tasks:**
  1. Give every HTTP request an id. Generate a random one, or accept a well-formed `X-Request-Id` of up to
     64 safe characters.
  2. Return the id in the `X-Request-Id` header and write it in the access line.
  3. Store the admitting request id in the job's first queue event, and show it in the page's technical
     details.
- **Done when:** tests show that:
  - the header round-trips;
  - malformed ids are replaced;
  - the id appears in the admission event;
  - log scans still find no key, case text or job id in access lines.

### 1.3 Cancel a job that is still queued

- **Goal:** the submitter can withdraw a case before the Runner takes it.
- **Tasks:**
  1. Add `POST /v1/jobs/{job_id}/cancel`.
     - A job that is still `QUEUED` becomes `CANCELLED` in a single `BEGIN IMMEDIATE` update, so a claim
       and a cancel can never both win.
     - Any other state returns `409 not_cancellable`. Core cannot pause or cancel a running job; document
       this.
     - Cancelling an already cancelled job returns 200 with the same record.
  2. Add the new state to the page (a button on queued jobs), the counts, the results and the state list
     in intake_queue.md.
- **Done when:**
  - a race test (claim and cancel in parallel, many rounds) never ends with a job that is both run and
    cancelled;
  - cancelled jobs never reach Core.
- **Owner test (ไทย):**
  1. ส่งหลายเคสพร้อมกัน
  2. กด "ยกเลิก" ที่เคสที่ยังรอคิว สถานะต้องเปลี่ยนเป็น "ยกเลิกแล้ว"
  3. เคสที่กำลังทำอยู่ต้องไม่มีปุ่มยกเลิก

### 1.4 Backup, restore and retention (needs the disk, D1 = paid)

- **Tasks:**
  1. Read Render's current disk docs to see what snapshots and restores already exist. Build only what is
     missing.
  2. If backups are needed, the Runner makes them, because it is the only owner of Core's files:
     - consistent copies with SQLite's online backup API into `<data>/backups/<timestamp>/`, the queue
       database in the same pass;
     - on a schedule, keeping the last N;
     - failures reported to Sentry.
  3. Add a restore drill to CI: restore a backup into a fresh container, then the smoke test's
     `--after-restart` check must pass.
  4. Retention: agree with the owner how long finished jobs stay. Prune application-queue rows first. Write
     a design note before deleting any Core data; check what `neuron_flow/storage.py` supports.
- **Done when:** the restore drill passes in CI, and the steps are written in intake_queue.md with a Thai
  summary.
- **Don't:** let the API process read Core's SQLite files (ADR-001).

### 1.5 Docs truth checks in CI (optional)

- Add a small test that:
  - every relative link in `README.md`, `CLAUDE.md` and `docs/**/*.md` resolves;
  - the README's test count matches the real count.
- It is cheap protection against the docs drifting away from the code.

### 1.6 New look for the web page (owner's "Nocturne" mockup)

- **Goal:** the page looks and flows like the owner's mockup (claude.ai design export, screens 1a–1c
  desktop and 2a–2c phone), using only what the system really does.
- **Why:** the owner asked for it on 2026-11-03. It was not in the first plan; it is added here so the
  plan stays true (see "How to use this file", point 4).
- **What was built (PR #18):**
  - a chat-style intake: type a case → a confirm card lists the real steps, their time limits and tries →
    "ยืนยันและส่ง" admits it → the result appears in the thread;
  - a Flow panel (the workflow as a graph, each step's result when the job ends) and the job's events
    (Trace);
  - a read-only settings view: steps and agents per workflow, the AI in use and how to change it in
    Render, the fixed decision rules, storage and limits;
  - phone layout: drawers for the case list, a bottom sheet for the Flow, a step strip under the header;
  - read-only step plans in the API (`workflows[].steps` in `/v1/status`, `plan` in the job view), so the
    page never hard-codes a workflow's shape.
- **Left out on purpose:** key, provider and retry fields, a "never ask" approval option and "edit JSON"
  (rules 4–7 in CLAUDE.md); free conversation and `/test`, `/eval`, `/backup` commands (Phase 4 and 1.4);
  live per-step progress (P2, see "Not now"); pause and cancel buttons (1.3 cancels queued jobs only).
- **Done when:** the owner opens the live page after the merge and the owner test below passes.
- **Status (2026-11-03):** done. PR #18 was merged at 01:43 Bangkok time, the checks on `main` passed at
  01:45, and the owner reported that the owner test passed on the live page at 01:56.
- **Owner test (ไทย):**
  1. เปิดหน้าเว็บ ใส่รหัสเข้าใช้ ต้องเห็น 3 ส่วน: รายการเคส (ซ้าย) แชท (กลาง) และ Flow (ขวา)
  2. กดตัวอย่าง "ถูกหักเงินซ้ำ" แล้วกด Enter ต้องขึ้นการ์ด "รอยืนยัน" ที่มี 4 ขั้นตอน และยังไม่มีเคสใหม่ในรายการซ้าย
  3. กด "ยืนยันและส่ง" ภายในไม่กี่วินาที ทุกขั้นต้องขึ้น ✓ และผลเป็น "รอคนตรวจ" พร้อมป้าย "ยกให้ดูก่อน"
  4. กด "ส่งซ้ำ (ทดสอบว่าไม่เกิดงานซ้ำ)" ต้องขึ้นข้อความว่าระบบรู้ว่าเป็นเคสเดิม และรายการซ้ายต้องไม่มีเคสเพิ่ม
  5. กดแท็บ "ตั้งค่า" ต้องเห็นตาราง 4 ขั้นตอน AI ที่ใช้อยู่ และกติกา "คนตัดสินทุกเคส" โดยไม่มีช่องให้พิมพ์อะไร
  6. เปิดบนมือถือ กด ☰ ต้องเห็นรายการเคส กดแถบขั้นตอนใต้หัว ต้องเห็น Flow เลื่อนขึ้นมาจากด้านล่าง

---

## Phase 2 — Milestone C: people review the work

Context: architecture.md §5 step 4 and ADR-004 (two-phase review as linked jobs). Today a job that needs a
person ends at `REVIEW_REQUIRED`, and nothing else can happen to it.

### 2.1 Personal access tokens and roles (replaces ADR-016)

- **Goal:** each person has their own credential. A decision records who made it, and one token can be
  revoked without changing everyone's key.
- **Design** (write ADR-017 first):
  - **Roles:**
    - `owner` manages tokens and can do everything;
    - `reviewer` reads jobs and decides reviews;
    - `submitter` creates and reads jobs, for n8n and other tools.
  - **Token format:** `nf_<token_id>_<secret>`.
  - **Storage:** keep only `sha256(secret)`, together with the id, display name, role, created_at,
    last_used_at and revoked_at. It goes in the queue database at schema version 2, with a tested 1 → 2
    migration; today `QueueStore.migrate` refuses any other version.
  - **Check:** look up the token id, then compare hashes with `hmac.compare_digest`. Keep today's limits
    on wrong keys.
  - **Issuing tokens:** the owner cannot run commands, so the web page gets an owner-only "จัดการผู้ใช้"
    section. There the owner creates a token (shown once), lists tokens and revokes them. The existing
    `NEURON_FLOW_ACCESS_KEY` becomes the owner's bootstrap key.
  - **Switch-over:** the shared key keeps working as `owner` during the switch, and the page explains the
    change in Thai.
- **Done when:** tests cover:
  - issuing a token and showing it only once;
  - revoking, which takes effect at once;
  - role checks on every route;
  - the limits on wrong tokens;
  - the migration;
  - no token or hash appearing in logs, responses or Sentry.
- **Owner test (ไทย):**
  1. สร้างรหัสผู้รีวิวในหน้า "จัดการผู้ใช้"
  2. เปิดหน้าต่างส่วนตัว แล้วใช้รหัสนั้นเข้าใช้
  3. กดเพิกถอนรหัส รหัสนั้นต้องใช้ไม่ได้ทันที
- **Don't:** build passwords, e-mail login or OAuth now. Note them in the ADR as later options.

### 2.2 Review ledger and decisions API

- **Tables:**
  - `reviews`: review_id, job_id (unique), version, state (`PENDING`, `APPROVED` or `REJECTED`),
    proposal_sha256, priority (`normal` or `elevated`), created_at, decided_at.
  - `review_decisions`, append-only: decision_id, review_id, version, reviewer_token_id, decision,
    final_category, reason, idempotency_key, request_sha256, created_at.
- **Creation:** when the Runner finishes a job as `REVIEW_REQUIRED`, it creates the review row in the same
  transaction as `finish()`.
- **API:**
  - `GET /v1/reviews?state=PENDING&limit=&before=`: elevated reviews first, then the oldest.
  - `GET /v1/reviews/{review_id}`.
  - `POST /v1/reviews/{review_id}/decisions` with
    `{decision: APPROVE|REJECT, final_category?, reason, expected_version, idempotency_key}`.
  - The reviewer always comes from the token, never from the body.
- **Rules:**
  - `final_category` must be one of the fixed categories. It defaults to the official rules proposal.
  - A reason is required, up to 500 characters.
  - `expected_version` other than the current version → `409 version_conflict`.
  - The same idempotency key with the same body → `200` with the same decision.
  - The same key with a different body → `409 idempotency_conflict`.
  - An already decided review → `409 already_decided`.
- **Done when:** the open P0 gates in architecture.md §9 pass:
  - a decision applies once per version;
  - unauthorised reviews are denied (no token, a revoked token, the wrong role);
  - 16 concurrent identical approvals produce one decision.
- **Status (2026-11-10): built before 2.1 (ADR-027),** because the independent review of that day found that a
  case could not be closed by a person (point 4; [evidence](evidence/2026-11-10-independent-review-response.md)).
  - As designed above, with three differences: the reviewer is `shared-access-key` with the role `owner` (the
    only credential until 2.1, and the only reviewer under D3's default); `review_id` is named after its job
    (`rev_<hex of the job id>`, so the access log hides it like a job id); the job itself moves to `APPROVED` or
    `REJECTED` in the same transaction (2.3 adds the linked job after `APPROVED`).
  - `final_category` is optional for `REJECT` (a rejected case may have no category); approving without one
    keeps the rules' suggestion.
  - Met: once per version, 16 identical approvals → one decision, 16 different decisions → one wins, all or
    nothing under an injected failure, no key or a wrong key denied (`tests/test_service_reviews.py`). Open
    until 2.1: a revoked token and the wrong role.

### 2.3 Linked phase-B job on approval (ADR-004)

- **Goal:** approval starts exactly one follow-up job, and rejection ends at `REJECTED`.
- **Tasks:**
  1. Add a catalog entry, for example `case_triage.v2.apply`. Its agent records the final routing
     (category, queue, who approved, decision id) and produces a receipt. It has no outward side effects.
  2. Write the decision row, the review's new state and the linked job's queue row in **one transaction**
     on the queue database. Use the idempotency key `review:<review_id>:v<version>`, so a replay can never
     create a second job.
  3. Add the job states `APPROVED → linked job QUEUED` and `REJECTED`. The job view links both ways.
- **Done when:**
  - approval creates exactly one linked job, also under concurrency;
  - a crash test shows the transaction is all or nothing;
  - rejection creates no job.
- **Since 2026-11-11:** built as the first route of the skill-handoff exchange
  ([H3](#skill-handoff-track-h1h5), ADR-030, [skill_handoff.md](skill_handoff.md)). The same one transaction, with
  the idempotency key `handoff:<source_job_id>:<route_id>` in place of `review:<review_id>:v<version>`; a review
  is decided once, so both name exactly one job. `case_triage.v2.apply` is started only by that route and refused
  at `POST /v1/jobs`.

### 2.4 Reviewer inbox on the web page

- **What it shows:** a "รอรีวิว" tab with elevated cases first. Each case shows:
  - the case summary;
  - the rules' suggestion;
  - the AI's second opinion, with its confidence and reason;
  - why it was raised;
  - the decision history.
- **What the reviewer does:** clicks "อนุมัติ" or "ไม่อนุมัติ", picks a category and writes a reason.
- **Constraints:** keep the strict CSP and no inline script, insert server data only as text, and make it
  work on a phone.
- **Owner test (ไทย):**
  1. ส่งเคสที่กฎกับ AI เห็นไม่ตรงกัน เคสต้องขึ้นบนสุดในแท็บ "รอรีวิว" พร้อมป้าย "ด่วน"
  2. กด "อนุมัติ" เลือกหมวด และใส่เหตุผล สถานะต้องเป็น "อนุมัติแล้ว" และมีงานต่อเนื่อง 1 งาน
  3. กดซ้ำ ต้องไม่เกิดงานที่สอง
- **Status (2026-11-10): built with 2.2** (ADR-027). The "รอรีวิว" list is a box in the left column, not a
  tab; each waiting case has a "ตัดสินเคสนี้" card under its proposal (the case summary, the rules' suggestion,
  the AI's second opinion and why it was raised are already above it). Checked in a headless browser on
  desktop and phone width; the owner test on the live page is left. Step 2's linked job waits for 2.3, so for
  now the owner test is:
  1. ส่งเคสตัวอย่าง "ถูกหักเงินซ้ำ" แล้วกด "ยืนยันและส่ง" เมื่อเคสขึ้น "รอคนตรวจ" ด้านซ้ายต้องมีกล่อง "รอรีวิว" และเคสนี้มีป้าย "ด่วน"
  2. เลื่อนลงในเคส จะเห็นการ์ด "ตัดสินเคสนี้" กด "อนุมัติ" เลือกหมวด "การเงิน / การชำระเงิน" พิมพ์เหตุผลสั้น ๆ แล้วกด "บันทึก: อนุมัติ"
  3. สถานะต้องเป็น "อนุมัติแล้ว" กรอบผลเป็นสีเขียว "คนตัดสินแล้ว: อนุมัติ → คิวตรวจเรื่องการเงิน" และเคสหายจากกล่อง "รอรีวิว"
  4. ส่งเคสอีกเคส แล้วกด "ไม่อนุมัติ" โดยไม่พิมพ์เหตุผล ต้องขึ้นข้อความให้เขียนเหตุผลก่อน และยังไม่มีอะไรถูกบันทึก

### 2.5 n8n intake and reviewer notifications (needs D3)

- **Intake:** an n8n workflow receives a case, by webhook, e-mail or LINE as the owner chooses. It calls
  `POST /v1/jobs` with a `submitter` token and an idempotency key built from the source message id, so
  n8n's own retries never create a second job.
- **Notifications:** n8n polls `GET /v1/reviews?state=PENDING` on a schedule and tells the reviewers on the
  owner's chosen channel ("มีเคสรอรีวิว N เคส ด่วน M เคส" plus a link).
  - Polling keeps the service free of outward calls, so ADR-007 does not apply.
  - Notifications carry counts and links, not case text.
- **In the repo:** store each n8n workflow as exported JSON in `integrations/n8n/`, with a README and with
  credentials removed.
- **Owner test (ไทย):**
  1. ส่งเคสจากช่องทางที่เลือก เคสต้องขึ้นในหน้าเว็บ
  2. ภายในไม่กี่นาที ผู้รีวิวต้องได้ข้อความแจ้งเตือน
- **Don't:** let n8n retry or order steps, decide reviews, or hold the owner token. n8n only receives and
  notifies.

### 2.6 Side-effect contract (ADR-007), before the first agent that changes something outside

- **When it is needed:** only when an agent would send an e-mail, call a ticket system, post a message or
  pay anything. Core retries interrupted steps, so an outward effect inside a step could happen twice.
- **Design:**
  1. The step records an *intended effect* with a deterministic `effect_id` in an outbox (application
     layer).
  2. A dispatcher outside Core performs it, using the provider's idempotency key when the provider has one.
  3. The dispatcher records the confirmation and never repeats a confirmed effect.
- **Tests** kill the process between "sent" and "recorded".
- **Done when:**
  - there are no duplicate effects where the provider supports idempotency;
  - where it does not, the at-most-once-or-flagged behaviour is documented.

### 2.7 Artifact store with hash checks (ADR-006), when needed

- **When it is needed:** an input or output exceeds Core's 1 MiB message limit (documents, attachments), or
  a reviewer must see it as a file.
- **Design:**
  - content-addressed files under `<data>/artifacts/sha256/<2 chars>/<rest>`;
  - jobs carry `{artifact_id, sha256, bytes}`;
  - `GET /v1/artifacts/{artifact_id}` is authorised by id, never by a user-supplied path;
  - every read re-checks the hash.
- **Done when:**
  - flipping one byte on disk makes the read fail loudly (an open P0 gate);
  - path tricks (`..`, absolute paths, symlinks) are refused.

### 2.8 Measure rules vs AI against reviewer labels

- **What it is:** each decision's `final_category` is a person's label. Add a scorecard-style report that
  compares the rules and the AI against reviewer labels:
  - every rate as numerator/denominator;
  - split by language.
- **Why:** this is the evidence ADR-010 asks for before the AI's role can change (owner decision D6).
- **Caveat:** say clearly that reviewer labels on synthetic cases are still not real-world accuracy.

---

## Phase 3 — `study_guide.v1`: the first-response study guide (the second domain)

**Why:**
- It is the owner's first-response rule ([design_philosophy.md](design_philosophy.md)).
- It is unrelated to triage, so it proves that a second domain needs zero Core changes (Milestone E,
  funding gate M4).

The design follows the proposal in design_philosophy.md.

**Paused by the owner on 2026-11-11.** No new study-guide work (E4, E6, or any other change to
`app/domains/study_guide/`) until the owner resumes it. What is built stays on the page, and its checks keep
running (the scorecard's eval gate, the robustness gate and the weekly link check), so a regression is still
caught. The skill-handoff track does not need it and does not edit it.

### 3.1 Topic catalog and verified resource library

- **Versioned data** in `app/domains/study_guide/catalog/`:
  - `topics_v1.json`: topic id, Thai and English names, example phrases and metaphors in both languages,
    prerequisite topics, level.
  - `resources_v1.json`: id, URL, title, what it is for, level (เริ่มต้น / กลาง / ลึก), language, topics
    covered, which parts to focus on, `verified_at`.
- **Seed** it from the table "แหล่งศึกษาเริ่มต้น" in design_philosophy.md, and re-check every link before
  adding it.
- **Weekly link check:** a scheduled GitHub Actions job (GitHub runners can reach the internet) checks every
  URL and fails loudly on broken links. It never removes entries by itself.
- **Versioning:** the library's hash is part of the agent version, like a prompt hash.
- **Status (2026-11-05): built in PR #32.** Details: [study_guide.md](study_guide.md).
  - 11 topics and 17 resources: every link of the seed table, with the roadmap.sh home page split into
    its four named roadmaps (AI Engineer, AI Agents, Prompt Engineering, System Design) and the Anthropic
    article at its current address. A test keeps every seed link in the library.
  - *Added to the plan when it was built:* each topic has a one-sentence summary in both languages (for
    detection and for honest out-of-scope answers); each resource also says who made it (`by`), what kind
    it is, and whether it is free or paid. Levels are stored as `beginner`/`intermediate`/`advanced` and
    shown as เริ่มต้น/กลาง/ลึก. A prerequisite may not be harder than the topic that needs it, so a path can
    go from prerequisites to the topic and from easy to hard at once.
  - `app/domains/study_guide/library.py` refuses a library that breaks any rule and lists every problem.
    One SHA-256 covers both files (canonical JSON); `Library.tag` (`v1@sha256:…`) is what 3.2 puts in the
    agent versions.
  - *Actions → Study library link check* runs every Monday, by hand, and on every push or pull request that
    changes the study guide, so a new link is checked before it is merged. Broken links fail the run;
    moved links and sites that refuse automated visits (401/403/429) are warnings, because they are not
    proof of a broken link. It never edits the library.
  - First runs on GitHub: 16 of 17 links opened on the push run, and the 17th (the Cooper PDF) answered
    "connection reset" on both attempts 5 s apart; 30 s later the pull-request run opened all 17. Network
    errors and 5xx are therefore retried twice (5 s and 20 s later) instead of once.
  - Not in the library on purpose: the owner's example "อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ", kept for the
    evaluation set (3.3) so detection is tested on a phrase it was not shown.
  - Gaps, honestly: one Thai resource (Thai MOOC); `plain_language` has only the ISO standard, whose full
    text is paid; `recommender_systems` has one advanced technical report.
- **Owner test (ไทย):**
  1. เปิด GitHub → Actions → *Study library link check* → รันล่าสุด
  2. เลื่อนลงไปที่หัวข้อ "ตรวจลิงก์คลังแหล่งเรียน (study library link check)" ต้องขึ้นคำว่า "ผ่าน"
  3. ตารางต้องมี 17 แถว แต่ละแถวมีชื่อหน้าที่เว็บตอบกลับมา และไม่มีแถวที่ขึ้น "❌ เสีย"

### 3.2 The workflow

```text
detect_topic (AI) ─► pick_resources (rules) ─► build_path (rules) ─► explain (AI) ─► prepare
```

- **`detect_topic`** maps the message to a topic id from the catalog, **or** to `out_of_scope`. It also
  gives a confidence (high, medium or low) and restates the request in one plain sentence for the person to
  confirm. The output is limited to the catalog's ids through the gateway, and the prompt lives in
  `app/llm/prompt_library/`.
- **`pick_resources`** chooses up to 5 resources for the topic, Thai first when one exists, and never
  anything outside the library.
- **`build_path`** puts prerequisites first, then goes from easy to hard. It says what to study first and
  what can wait.
- **`explain`** writes a plain-language explanation that may refer only to the selected resource ids.
  **The AI never writes URLs. Code inserts them from the library**, so a made-up link is impossible.
- **`prepare`** builds the answer in layers (one-line summary → steps → details), adds the confidence, and
  asks "เข้าใจถูกไหม".
- **Validators** check that:
  - every resource id is in the selection, and there are at most 5;
  - each resource has a purpose, a level and a language;
  - every step cites a selected resource;
  - out-of-scope answers say honestly what the system can help with.
- **Wiring:**
  - the mock provider supports it, so every test runs offline;
  - it is registered in the workflow catalog;
  - a study guide is informational, so its job ends `COMPLETED` without review. Write this decision down.
- **Status (2026-11-05): built in PR #33.** Details: [study_guide.md](study_guide.md#the-workflow-roadmap-32).
  - The five steps run on the unchanged Core: `detect_topic` (AI) → `pick_resources` → `build_path` →
    `explain` (AI) → `answer`. The last step's id is `answer` (agent `study.prepare`), so the page can tell
    it apart from triage's `prepare`.
  - *Changed when it was built:* "Thai first" became "the person's language first". An English request got
    a Thai course first, which helps nobody, and a Thai request still gets Thai resources first. The topic's
    own resources take at most 3 of the 5 places; the rest go to prerequisite topics, nearest first. A
    prerequisite topic that gets no place is named in the answer.
  - Detection also returns the message's language, so the answer (labels, purposes, the confirm question)
    is in Thai or English.
  - The prompts are completed from the library before each call (ADR-019). Detection may only answer a
    catalog id or `out_of_scope`; the explanation gets one note field per step. The AI is never shown a URL,
    and any AI text with a link is refused (an off-contract answer, retried, then the fallback).
  - Failures: detection unavailable → `not_understood`, which says so and lists the topics; explanation
    unavailable → the library's own text; a bad key → the step fails loudly. A job frozen with another
    library fails with `LibraryChanged`, and Core refuses changed agent versions.
  - The decision to end `COMPLETED` is ADR-018 in architecture.md.
  - In the catalog as `study_guide.v1`, so the API accepts `{"message": …}`. The page's settings tab lists its
    steps; the box on the page came with 3.4.
  - `examples/study_guide_demo.py` runs in *Core logic tests* and shows four answers on the run page.
  - The mock provider now has one simulation per prompt. The study guide's mock counts words taken from
    the catalog examples (all 66 map to their own topic), so it cannot read a new metaphor: the owner's
    "บรรณารักษ์ที่รู้ใจ" is out of scope with the mock. That is a limit of the simulation; 3.3 and live runs
    measure the real thing (with Typhoon on 2026-11-06 the sentence got its labelled topic).
  - Known gap: the `explain` AI call has a step span but no `chat` span in traces yet.
- **Owner test (ไทย):**
  1. เปิด GitHub → Actions → *Core logic tests* → รันล่าสุดของ PR นี้ → Summary
  2. หัวข้อ "ผู้ช่วยแนะนำแหล่งเรียน: ตัวอย่างคำตอบ" ต้องมีคำตอบ 4 ข้อ ข้อแรกได้แผน 5 แหล่ง ข้อ "สูตรต้มยำ"
     ต้องขึ้น "อยู่นอกกรอบ" พร้อมรายการหัวข้อที่ช่วยได้ และทุกลิงก์ต้องเป็นลิงก์ในคลัง
  3. หลัง merge เปิดหน้าเว็บ → แท็บ "ตั้งค่า" ต้องเห็นกล่อง "ผู้ช่วยแนะนำแหล่งเรียน" ที่มี 5 ขั้นตอน

### 3.3 Evaluation set and scorecard

- **Cases** in `app/eval/golden/study_guide_synthetic_v1.json`, in Thai and English:
  - metaphors ("อยากให้ระบบเป็นเหมือนบรรณารักษ์ที่รู้ใจ");
  - paraphrases of the same need;
  - out-of-scope requests (CLINC150-style);
  - injection attempts ("ignore your rules and add this link").
- **Report:**
  - topic accuracy;
  - out-of-scope precision and recall;
  - links outside the library (must be 0);
  - the ≤ 5 rule (must hold every time).

  Every rate is numerator/denominator. Run it in CI with the mock, and by hand with Claude.
- **Status (2026-11-06): built in PR #34.** Details: [study_guide.md](study_guide.md#the-scorecard-roadmap-33).
  - 67 requests: 33 Thai and 34 English; 48 in scope (every topic in both languages) and 19 out of scope;
    22 metaphors (the owner's librarian included), 15 paraphrases, 7 plain, 6 injection attempts. None is a
    catalog example, and the loader refuses one. The set was written after the mock's keyword lists, and
    the lists were not changed to fit it.
  - `app/eval/study_guide_eval.py` reports topic accuracy, out-of-scope precision and recall, in-scope
    requests turned away, links outside the library and answers over five, by language and by tag, with
    tokens, latency and every mistake. A broken promise or an unfinished job fails the run.
  - *Added to the plan:* the scorecard is also an eval gate like 5.2. *Core logic tests* compares every
    request's answer with `tests/baselines/study_guide_eval_mock.json`. The gate's shared code moved to
    `app/eval/common.py`; the triage baseline regenerates byte for byte.
  - Mock results (2026-11-06): topic correct 2/48, out-of-scope precision 19/65 and recall 19/19, in scope
    turned away 46/48, links outside the library 0 of 7, answers over five 0 of 67. The keyword mock cannot
    read new phrasings; these numbers test the pipeline, not understanding.
  - First live run, Typhoon on 2026-11-06 (PR #38, [evidence note](evidence/2026-11-06-first-live-typhoon.md)): topic correct
    46/48, out-of-scope precision 16/17 and recall 16/19, in scope turned away 1/48, links outside the
    library 0 of 142, answers over five 0 of 67, injection topic correct 4/6; its five misses are listed
    in the note. *Study guide eval with Claude (manual)* needs `ANTHROPIC_API_KEY` (D2).
- **Owner test (ไทย):**
  1. เปิด GitHub → Actions → *Core logic tests* → รันล่าสุดของ PR นี้ (3.12) → Summary
  2. หัวข้อ "ผลวัดผู้ช่วยแนะนำแหล่งเรียน (study guide scorecard)" ต้องขึ้น "ลิงก์นอกคลัง 0" และ "คำตอบที่เกิน 5 แหล่ง 0"
     พร้อมข้อความ "คำมั่น … เป็นจริงทุกคำตอบ"
  3. ใต้ตารางต้องมี "ด่านตรวจผลรายเคส (eval gate): ผ่าน" ที่บอกว่าทั้ง 67 เคสตอบเหมือนเดิม
  4. ลองกับ AI จริงได้ฟรี: Actions → *Study guide eval with Typhoon (manual)* → Run workflow → limit = 5
     (หรือ *Study guide eval with Claude (manual)* เมื่อมี API key แล้ว, D2)

### 3.4 Study guide on the web page

- **The page:** a form, "อยากเรียนเรื่องอะไร". The answer shows the summary first, with "ดูขั้นตอน" and
  "ดูรายละเอียด" to expand.
- **Status (2026-11-08): ✅ built and merged in PR #39 (`cf06f4d`); the owner's test on the live page passed
  on 2026-11-08, with the mock AI.** Details:
  [study_guide.md](study_guide.md#the-page-roadmap-34) and [intake_queue.md](intake_queue.md#web-page).
  - *Where the box is:* a switch above the message box, "เคสลูกค้า" or "อยากเรียน". In study mode the box
    asks "อยากเรียนเรื่องอะไร", accepts 4–500 characters, offers four examples and sends with Enter (button
    "ถาม"). The examples are the four requests of `examples/study_guide_demo.py`, so the run page of *Core
    logic tests* shows what each one answers. Opening a case or a question from the list switches the box to
    that kind. The switch is temporary: the router (4.2) will choose by itself.
  - *Changed from the plan:* a question is sent at once, without the confirm card that cases have (ADR-023).
    It decides nothing (ADR-018), and the answer itself asks "เข้าใจถูกไหม", with a "แก้คำถาม" button that puts
    the question back in the box. The settings tab states the rule; a case still waits for "ยืนยันและส่ง".
  - *The layers:* (1) always shown: the one-line summary, what the system understood with its confidence
    and "เข้าใจถูกไหม", the topic and its level, where to start, and the most important resource when that is
    a different one (design_philosophy.md, first-response rule 4); (2) "ดูขั้นตอนการเรียน": every resource in
    order with its priority, level, language, cost, kind and author, what it is for, which parts to read
    first, and the AI's note; (3) "ดูรายละเอียด": why this order, background topics left out by the budget
    of 5, where the explanation came from and why, masked personal data, the library tag and rules version,
    the five steps with their results, and the technical record. Out of scope and "could not understand"
    list the 11 topics the guide covers instead of a plan. Labels come from the answer's codes, in Thai;
    the answer's own texts stay in the person's language.
  - *Also added:* `/v1/status` gives the question limits (`message_min_chars`, `message_max_chars`); the
    Flow panel says what each study step produced and ends "ตอบแล้ว · ไม่ต้องรอคนตรวจ"; the settings tab
    explains how to switch the online page to Typhoon (free) or Claude, and back (see 0.4).
  - *Honest about the mock:* with the mock AI the page says it is a keyword simulation and that a new
    metaphor such as "บรรณารักษ์ที่รู้ใจ" is answered as out of scope, and points to the settings tab.
  - *Checks:* `tests/test_web_page.py` (9 tests): every example passes its input contract, and the study
    examples answer with the mock as this owner test says; both limits in `/v1/status`; a Thai name for
    every step of every workflow and Thai words for every answer code, equal to the study guide's own Thai
    labels; no HTML insertion, no inline script or style; links only to https addresses, opened in a new
    tab with `rel="noopener noreferrer"`; the script parses (Node.js, present on GitHub's runners). Fed
    deliberately broken copies of the page, the tests failed every time (8 of 8). A headless-browser
    walkthrough (desktop 1440 and 1280 px, tablet 1024 px, phone 390 px) covered every state, including AI
    unavailable, the library's own text, masked personal data, and a failed, queued and running question,
    with no console errors, CSP violations or horizontal overflow.
  - *Phase gate:* zero Core changes (`git diff main -- neuron_flow/` is empty in PR #39); every validator
    was tested in 3.2; the scorecard is recorded (3.3, mock in CI and Typhoon by hand). Both eval gates
    still pass unchanged.
- **Owner test (ไทย)** หลัง merge รอ Render ขึ้นเวอร์ชันใหม่ประมาณ 3–5 นาที แล้ว:
  1. เปิดหน้าเว็บ ใส่รหัสเข้าใช้ เหนือช่องพิมพ์ต้องมีปุ่ม "เคสลูกค้า" กับ "อยากเรียน" กด "อยากเรียน"
     ช่องพิมพ์ต้องขึ้นว่า "อยากเรียนเรื่องอะไร" และมีตัวอย่าง 4 ปุ่ม
  2. กดตัวอย่าง "รั้วกั้น AI" แล้วกด Enter ภายในไม่กี่วินาทีต้องขึ้นกล่องคำตอบ: สรุป 1 บรรทัด, "ระบบเข้าใจว่า … เข้าใจถูกไหม",
     แหล่งที่ "เริ่มที่" กับแหล่งที่ "สำคัญที่สุด" และ "ทั้งหมด 5 แหล่ง"
  3. กด "ดูขั้นตอนการเรียน" ต้องเห็น 5 แหล่งเรียงกัน ทุกแหล่งบอกว่าใช้ทำอะไร ระดับไหน ภาษาอะไร ฟรีหรือเสียเงิน แหล่งแรกมีป้าย
     "เริ่มที่นี่" และกดชื่อแหล่งแล้วลิงก์เปิดในแท็บใหม่ จากนั้นกด "ดูรายละเอียด" ต้องเห็นเหตุผลที่เรียงแบบนี้และ 5 ขั้นตอนที่ระบบทำ
  4. กดตัวอย่าง "สูตรต้มยำ (นอกกรอบ)" แล้วกด Enter ต้องขึ้น "อยู่นอกกรอบ" พร้อมรายการ 11 หัวข้อที่ผู้ช่วยแนะนำได้
  5. กดตัวอย่าง "บรรณารักษ์ที่รู้ใจ" แล้วกด Enter
     - ถ้าช่อง AI มุมซ้ายล่างขึ้นว่า "AI จำลอง": ต้องขึ้น "อยู่นอกกรอบ" พร้อมกล่องสีเหลืองบอกว่า AI จำลองอ่านคำเปรียบไม่ออก
       (เป็นข้อจำกัดที่หน้าเว็บบอกตรง ๆ ไม่ใช่ระบบพัง)
     - ถ้าเปิด Typhoon แล้ว (แท็บ "ตั้งค่า" → "AI ที่ใช้อยู่" มีขั้นตอน): ต้องได้แหล่งเรียนไม่เกิน 5 แหล่ง ทุกแหล่งบอกว่าใช้ทำอะไร
       ระดับไหน ภาษาอะไร และควรเริ่มอันไหนก่อน
  6. กด "แก้คำถาม" คำถามเดิมต้องกลับไปอยู่ในช่องพิมพ์ แล้วกด "เคสลูกค้า" ส่งเคสตัวอย่าง เคสต้องยังขึ้นการ์ด "รอยืนยัน" เหมือนเดิม
- **Phase gate:**
  - zero Core changes (show the Core diff in the PR);
  - every validator tested;
  - the scorecard recorded.

---

## Phase 4 — The plain-language front door

**Why:** design_philosophy.md ("ลำดับการทำงานเมื่อมีคำสั่งภาษาธรรมดาเข้ามา") says people should not need to know
workflow types.

### 4.1 The frame

- **Extend each catalog entry** in `app/services/workflows.py` with:
  - a plain Thai name and description;
  - example requests in Thai and English;
  - the required input fields;
  - for each field, a simple question to ask when it is missing.
- **Versioning:** the frame is versioned data with a hash, like a prompt.
- **`GET /v1/frame`** lists what the system can do, in plain words, for the page and for out-of-scope
  answers.

### 4.2 `intake.route.v1`: the router

- **Steps:**
  1. **`understand` (AI):** turns the message into one task id from the frame, or `out_of_scope`. It also
     returns a confidence, the extracted fields, the missing fields and a plain restatement.
  2. **`check` (rules):** the task must exist, and the fields must pass that workflow's own `check_input`.
  3. **`prepare`:** gives exactly one of these:
     - an honest out-of-scope answer that lists what is possible;
     - **one** simple question for a missing field;
     - a restatement to confirm, when confidence is low;
     - a proposal that is ready to run.
- **The router never runs the task itself.**
  - When the person confirms ("ใช่ ทำเลย"), the application admits the task as a linked job through normal
    admission. This is pattern B in its simplest form.
  - A follow-up answer is a new router job that carries the previous router job id. The application copies
    the earlier frozen output into the new job's input, so each Core job stays self-contained.
- **First-response rule:** when the message is about technology or a logic system, the proposal also
  offers a study guide ("เสนอเอง").

### 4.3 Layered answers

- One presenter in `app/services/results.py` turns any result into a one-line summary, steps and technical
  details. The page, the API and later the MCP server all use it.

### 4.4 Chat-style page

- **Already there (1.6):** the chat layout, the message box, the thread and a confirm card. Today the box
  takes case text only and every message becomes a `case_triage` draft.
- **The page:** a message box and a thread showing router answers, questions, confirmations, and links to
  the jobs they created. Thai comes first; English is accepted.
- **Phase gate:**
  - paraphrases map to the same task (for example "เข้าระบบไม่ได้" and "ล็อกอินไม่ผ่าน");
  - out-of-scope requests are refused;
  - injection attempts cannot create a job without the confirm step;
  - nothing runs without validation;
  - zero Core changes.

  Report the rates honestly, and set targets only after the first measured run.
- **Owner test (ไทย):**
  1. พิมพ์ปัญหาเป็นภาษาธรรมดา ระบบต้องเล่ากลับว่าเข้าใจว่าอะไร และถามยืนยันก่อนทำ
  2. พิมพ์ข้อมูลไม่ครบ ระบบต้องถามกลับ 1 คำถาม
  3. พิมพ์เรื่องนอกกรอบ ระบบต้องบอกตรง ๆ ว่าช่วยอะไรได้บ้าง

---

## Phase 5 — Milestone D: tracing and evaluation gates

### 5.1 OpenTelemetry tracing to Honeycomb

- **Form:** an optional adapter in `app/observability/`, like Sentry. Core stays dependency-free, and
  tracing is off unless it is configured. *Changed when it was built:* the plan said the OpenTelemetry SDK
  would be an optional extra; a small standard-library OTLP/HTTP JSON exporter was built instead (ADR-017),
  because the spans are built after the job and the SDK's packages would add dependencies for features this
  service does not use.
- **Spans:**
  - each HTTP request (route label and status, no query string);
  - each job (queue wait, run time, status);
  - each step and each AI call (model, served model, input and output tokens, latency), following the
    OpenTelemetry GenAI semantic conventions.

  Step and AI spans are built afterwards from the step timeline and the AI step's output, so nothing has to
  be exported from Core's child processes.
- **Privacy:** never put case text, prompts, answers or keys in spans. A test scans the exported spans.
- **Done when:** one job shows up in Honeycomb as one trace with its steps, and turning tracing off changes
  no result.
- **Status (2026-11-03): built in PR #30.** Details: [observability_tracing.md](observability_tracing.md).
  - `HONEYCOMB_API_KEY` turns it on. The API makes a span for every `/v1` request; a request that admits a
    job stores its span in the `job.queued` event. After the outcome, the Runner builds the job's spans from
    the queue record, Core's step events and the AI view: job → queue wait and run → one span per step
    attempt → the AI call (GenAI attributes, tokens, latency).
  - Only allow-listed ASCII attributes can be sent. `tests/test_tracing.py` puts sentinel text in a case
    and scans every request body for it, the case id, the prompt, the AI rationale and both keys.
  - Turning tracing off changes no result: a test runs the same cases with and without it and compares
    statuses, reviews, steps, AI answers and histories.
  - *Actions → Tracing check* sends the service's traces to the OpenTelemetry Collector (the reference
    OTLP receiver) on every push and checks the trace of the smoke-test case. Its summary shows the trace.
  - `/v1/status` → `tracing` and the page's settings tab show whether tracing is on, where it sends and
    how the last export went. A job's `trace_id` is in `GET /v1/jobs/{job_id}` and the page.
  - **Confirmed in Honeycomb (2026-11-03,
    [evidence note](evidence/2026-11-03-first-trace-honeycomb.md)):** the owner's first case on Render
    arrived as one trace of 9 spans with the designed parent links, from both processes, and the dataset's
    52 columns hold no case text, prompt, answer or key. The first case after a restart took 10.5 s, almost
    all of it inside the first two step attempts.
  - Found by that check and fixed after it: no step carried its agent version, because the queue's spec
    lacks the `agent_versions` Core records on submit. The Runner now reads them from Core, and the
    end-to-end test checks them. The key setup steps were also unclear (the 32-character Key ID was
    pasted instead of the full 64-character key, and Honeycomb answered 401); the page and
    observability_tracing.md now say which value to copy.
- **Owner test (ไทย):**
  1. ใส่ `HONEYCOMB_API_KEY` ใน Render ตามขั้นตอนใน [observability_tracing.md](observability_tracing.md)
     (หัวข้อ "เปิดใช้อย่างไร")
  2. เปิดหน้าเว็บ → แท็บ "ตั้งค่า" กล่อง "เส้นทางงานใน Honeycomb" ต้องขึ้น "เปิด — ส่งไป api.honeycomb.io"
  3. ส่งเคสตัวอย่าง 1 เคส รอจนขึ้น "รอคนตรวจ" แล้วกด "รายละเอียดเชิงเทคนิค" ต้องเห็นรหัสเส้นทาง (trace id)
  4. เปิดเส้นทางนั้นใน Honeycomb ต้องเห็น 9 แถบเรียงเป็นชั้น ตั้งแต่ `POST /v1/jobs` ลงไปจนถึง `chat …`

### 5.2 Evaluation gate in CI

- **How it works:** commit the mock scorecard as a baseline. CI runs `--compare-with` and fails when any
  per-case answer changes, unless the same PR updates the baseline and explains why.
- **Prompt or model changes** also attach a live run made by hand (the 0.3 workflow).
- **Status (2026-11-03): built in PR #27.**
  - The baseline is `tests/baselines/shadow_eval_mock.json`: every case's answer with the mock AI, one case
    per line, plus the case set, prompt and model that produced it. It sits in `tests/`, so a
    baseline-only change does not redeploy Render.
  - "Any per-case answer" means more than the AI outcome that `candidate_gate` compares: the rules'
    category, the AI's status, category, reason, confidence and attempts, the agreement, the review
    priority and reasons, the job status and the case text. A changed case set, prompt or model also fails.
  - *Core logic tests* runs `--compare-with` on every push and pull request, after the unit tests and even
    when they failed, so the run page always lists the differences. The unit test
    `test_the_committed_baseline_matches_a_fresh_mock_run` makes the same check locally.
  - `--write-baseline` regenerates the file. CI cannot check that a pull request explains why; that rule
    is in CLAUDE.md §5 (definition of done).
  - Details: [case_triage_v2_shadow.md](case_triage_v2_shadow.md#the-eval-gate-roadmap-52).
- **Owner test (ไทย):**
  1. เปิด PR #27 บน GitHub แล้วกดแท็บ Checks → *Core logic tests* (3.12)
  2. กด Summary ของรันนั้น เลื่อนลงล่างสุด ต้องเห็นหัวข้อ "ด่านตรวจผลรายเคส (eval gate): ผ่าน" และบอกว่าทั้ง 61 เคสตอบเหมือนเดิม

### 5.3 Queue and run-time metrics

- `/v1/status` and the page show:
  - the waiting count and the oldest waiting age;
  - the median and slowest run time per workflow type over the last N jobs;
  - failure counts by reason.
- **Status (2026-11-03): built in PR #26.**
  - `app/services/metrics.py` computes the figures from the queue database on every status request, with
    no new state: N is the newest 100 jobs that ran to an outcome (cancelled jobs never ran). The median
    and slowest queue wait (admitted → first claim) are shown too, next to the run time (first claim →
    outcome), and `recovered` counts jobs a new Runner took over, whose run time includes that gap.
  - The page shows the oldest waiting age under the counts, the usual run time of a new case in the
    system box ("เวลาต่อเคส"), and a "ตัวเลขการทำงาน" panel in the settings tab. The field reference is in
    [intake_queue.md](intake_queue.md#queue-and-run-time-figures-roadmap-53).
  - Not per step: Core runs a job as one loop, so per-step timing is in the traces (5.1), not here.
- **Owner test (ไทย):**
  1. เปิดหน้าเว็บ ช่อง "เวลาต่อเคส" ซ้ายล่างต้องขึ้น "ยังไม่มีข้อมูล" (ถ้าระบบเพิ่งตื่นและยังไม่มีเคส)
  2. ส่งเคสตัวอย่าง 2–3 เคส แล้วกดยืนยัน รอจนขึ้น "รอคนตรวจ" ช่อง "เวลาต่อเคส" ต้องเปลี่ยนเป็น "ปกติ … วิ"
  3. กดแท็บ "ตั้งค่า" เลื่อนลงล่างสุด ต้องเห็นกล่อง "ตัวเลขการทำงาน" ที่บอกจำนวนเคส เวลารอคิว และเวลาทำงาน
     (ปกติ / นานสุด) และแถว "สาเหตุที่ไม่สำเร็จ" ต้องขึ้นว่า "ไม่มี"

---

### 5.4 Robustness benchmark, stage 1 (open and synthetic edge cases)

- **Goal:** test the core logic beyond the developer's own happy paths. Use the corpora that developers
  commonly use to break software, plus hard Thai and English cases written for this system. Make the result
  a gate in CI. The full three-stage plan is in [benchmarking.md](benchmarking.md).
- **Why:** the owner asked for testing "beyond the private lab" with open datasets (2026-11-07). The existing
  scorecards use 61 and 67 developer-written cases that follow the happy paths.
- **Status: ✅ built in PR #41 and merged on 2026-11-07,** after the owner checked the run page.
  - `tests/robustness/`:
    - 270 synthetic items across six layers (intake, rules, masking, AI replies, Core contracts, whole jobs
      through Core);
    - an extract of BLNS, JSONTestSuite, CLINC150 and BANKING77, pinned to upstream commits with SHA-256 and
      licences (`NOTICE.md`, ADR-024);
    - the runner `bench.py`.
  - *Core logic tests* runs it and compares every outcome with `tests/baselines/robustness_v1.json`.
  - The 116 rules items are also a case file that the manual Typhoon and Claude scorecards can run
    (`case_set: robustness_edge_v1`).
  - First run: 206/270 own items pass, with 8 bugs, 45 gaps and 11 notes; the 4,680 sweep checks broke no
    promise ([evidence note](evidence/2026-11-07-robustness-stage1.md)).
- **Done when:** the owner has seen the summary on the run page (owner test). The benchmark itself is tested:
  8 unit tests, and identical outcomes on Python 3.10, 3.12 and 3.13.
- **Owner test (ไทย):**
  1. เปิด PR #41 กดแท็บ Checks เลือก *Core logic tests* (3.12) แล้วกด Summary
  2. เลื่อนหา "ด่านความทนทาน (Robustness benchmark ขั้นที่ 1)" ต้องเห็นตาราง 6 ชั้น, "ปัญหาร้ายแรง (bug) **8**"
     และ "ด่านตรวจผลรายรายการ (gate): **ผ่าน**" (ตั้งแต่ขั้น 5.5 ตัวเลข bug บนหน้าสรุปของ PR ใหม่เป็น **0**)
  3. (ไม่บังคับ ฟรี) แท็บ Actions เลือก *Shadow eval with Typhoon (manual)* แล้วกด Run workflow เลือก case_set
     `robustness_edge_v1` ต้องเห็นผล 116 เคส แยกกฎกับ AI
- **Don't:** use real people's text (rule 9, ADR-024), or call a real AI from CI.

### 5.5 Fix what stage 1 found

- **Status (2026-11-08): the 8 bugs are fixed in PR #42**, merged the same day (the owner asked to start;
  after the deploy the owner's case on the live page still reached review); deciding the gaps (task 3) is
  next.
  - Re-run: 215/270 own items pass, with 0 bugs, 44 gaps and 11 notes; 0 of 4,680 sweep checks broke a
    promise; identical on Python 3.10, 3.12 and 3.13.
  - Exactly 9 items changed in the baseline: the 8 bugs and the gap SYN-COR-041
    ([evidence note](evidence/2026-11-07-robustness-stage1.md), "Re-run after the fixes").
- **Tasks:**
  1. **Intake** ✅:
     - `routes._submit` and `_cancel` turn any `ValueError` from `decode()` into 400 `invalid_json`.
       `SpecError` is a `ValueError`, so this covers the int-digit limit even without the Core change in task 4.
     - `admit()` converts a `SpecError` from the fingerprint into 400 `invalid_input`.
  2. **Gateway** ✅: `parse_answer` replaces a lone surrogate in a free-text field with U+FFFD, so Core can
     store the answer.
     - This differs from the plan, which was to refuse the answer (`InvalidModelOutput`, then "rules only").
       Refusing would cost the case the AI's second opinion for one broken character, while the rest of the
       answer is valid and still checked.
     - A lone surrogate in a fixed-choice field cannot match the choices, so that answer is still refused.
     - The study guide's answers go through the same gateway, so they are cleaned the same way.
  3. Decide each gap and write the decision down.
     - The 27 original rules gaps are addressed by E2 in PR #64: versioned Thai keywords, whole-word
       English matching and matching-only normalization; each is listed as fixed or kept as a measured
       limit in the [E2 evidence](evidence/2026-11-11-e2-rules-v2.md). `case_triage.v1` retains the original
       demonstration; the shadow workflow and the benchmark rules layer use v2.
     - Still proposed for the other gaps:
     - strip or refuse bidi controls in case text and AI text;
     - count visible characters for the minimum length;
     - refuse an empty rationale, as the study guide does;
     - NFC-normalize text before the fingerprint, as an ADR, because it changes which requests count as the
       same.
     A masking change is a new `REDACTION_VERSION`.
  4. **Core** ✅ (ADR-025): `decode()` raises `SpecError` for everything it cannot read, including the int-digit
     limit and a `str` holding a lone surrogate (SYN-COR-040, SYN-COR-041).
     - One function, in its own commit in PR #42; Core version 0.4.1.
     - The app guards in task 1 do not depend on it. If the owner does not want a Core change, that commit
       is dropped before the merge and the baseline regenerated; only SYN-COR-040 and SYN-COR-041 would
       then fail again.
- **Done when:**
  - the 8 bug items pass;
  - the regenerated baseline says why each outcome changed;
  - a test covers each fixed path, including the end-to-end "AI replies with a lone surrogate, the case still
    reaches review".
- **Owner test (ไทย):**
  1. เปิด PR #42 กดแท็บ Checks เลือก *Core logic tests* (3.12) แล้วกด Summary
  2. หัวข้อ "ด่านความทนทาน (Robustness benchmark ขั้นที่ 1)" ต้องขึ้น "ผ่าน **215/270**", "ปัญหาร้ายแรง (bug) **0**"
     และ "ด่านตรวจผลรายรายการ (gate): **ผ่าน**"
  3. หลังสั่งรวม (merge) Render จะขึ้นเวอร์ชันใหม่ เพราะรอบนี้แก้โค้ดที่ระบบใช้จริง (แผนฟรี: เคสที่ค้างในคิวจะหาย)
     รอสักครู่ แล้วเปิด https://neuron-flow.onrender.com ส่งเคสปกติ 1 เคส ต้องถึงขั้น "รอคนตรวจ" เหมือนเดิม

### 5.6 Stage 2: open benchmarks

- **What:**
  - CLINC150 (with 1,000 out-of-scope requests), BANKING77, and MASSIVE 1.1 `th-TH` with `en-US`
    (parallel sentences, CC BY 4.0);
  - a fixed, seeded sample, scored with the existing scorecards (`--golden`) against Typhoon by hand;
  - accuracy, macro-F1, out-of-scope recall, the false in-scope rate of the study guide, and EN↔TH agreement.
  Details: [benchmarking.md](benchmarking.md), "Stage 2".
- **Done when:**
  - a manual workflow downloads the pinned sources, checks their SHA-256 and builds the case files at run
    time (nothing large is committed);
  - the mock run passes in CI;
  - the first Typhoon run is in an evidence note.
- **Don't:** compare with published leaderboards (different labels), or present mapped labels as ground truth.
- **Status (2026-11-11, PR #66):** built with 5.9, because the owner asked for the system's limits on public
  benchmark data. `tests/open_benchmarks/build_sets.py` downloads the pinned sources (GitHub commits and the
  MASSIVE release archive), refuses any SHA-256 it does not expect, and builds 300 CLINC150 requests, 300 BANKING77
  requests and 150 MASSIVE Thai/English pairs (fewer than the 300 per language planned, to keep a Typhoon run
  under an hour); `manifest_v1.json` holds every case file's SHA-256. The workflow *Auto-approve limits (open
  benchmarks + hard set)* runs them (the mock on pull requests that change the lane, Typhoon by hand). The first
  Typhoon run, with accuracy, per-category F1, out-of-scope recall, EN↔TH agreement, rules vs AI and latency, is in
  the [evidence note](evidence/2026-11-11-autosend-limits.md). Not done: the study guide's false in-scope rate,
  because the owner paused the study guide.

### 5.7 Stage 3: attacks, personal data, load and live drift

- **What:**
  - `deepset/prompt-injections` (Apache-2.0) and Thai versions inside cases. The structural promises are
    100% gates; the AI's flip rate is reported.
  - A generator of invented Thai personal data, scanned in the fake provider's request bodies (leak rate per
    kind).
  - Bursts, duplicate storms and kills in *Service container*.
  - A weekly Typhoon run of the edge set, compared with the week before.
  Details: [benchmarking.md](benchmarking.md), "Stage 3".
- **Owner decision:** turning on the weekly schedule. It uses the existing `TYPHOON_API_KEY` secret, and the
  data is synthetic only.
- **Status (2026-11-11, PR #66):** the first injection measurement only. BIPIA's 75 test attacks (MIT; `deepset`
  is on Hugging Face, which this session cannot reach) were placed in the hard set's 20 clear cases and compared
  with the same cases without them, and the hard set holds 16 Thai and English attempts to steer the category or
  claim an approval. The structural promise held: no job was decided without a person. The AI's answers are in
  the [evidence note](evidence/2026-11-11-autosend-limits.md). Personal data, load, restarts and drift are not
  built.

### 5.8 Local open-model lane (asked by the owner on 2026-11-08)

- **Goal:** a real model that this project runs itself, at no cost and without sending anything to an AI
  company, so the scorecards can run as often as needed.
- **Why:**
  - Typhoon's free API is a beta research showcase that collects usage data (synthetic data only), and it
    could change or end. Claude needs D2.
  - An open-weight model file with a pinned SHA-256 is a fixed yardstick: the same file and settings give the
    same answers, so two runs can be compared.
- **Built (PR #46, ADR-026):**
  - the `local` provider (`app/llm/config.py`, `providers/openai_compat.py`): the OpenAI format, by default
    `http://127.0.0.1:8080/v1`, an optional key (`NEURON_FLOW_LOCAL_API_KEY`), and a model id that names the
    file, `<name>:<first 12 hex digits of its SHA-256>`;
  - `.github/scripts/fetch_model.py`: the model file from Hugging Face at one commit, its SHA-256 checked
    (the pinned one, or the publisher's with a warning on the run page), kept in the Actions cache;
  - *Local open model eval* (`.github/workflows/local-model-eval.yml`): llama.cpp's server built from a pinned
    commit (cached), Typhoon 2.5 Qwen3 4B Q4_K_M served on 127.0.0.1 with greedy decoding, the connection
    check, then both scorecards. Pull requests that change `app/llm/`, the workflow or its scripts get a
    smoke run (5 cases, 5 requests); *Run workflow* runs everything, or one scorecard.
- **Status (2026-11-08):** the PR's first smoke run answered through the whole path in about 7.5 minutes,
  most of it the first build (now cached): triage AI correct 5/5 (rules 3/5, both rule mistakes raised), study
  guide topic correct 5/5, 0 of 10 links outside the library, no AI step unavailable. The model file is now
  pinned (commit `386874d02430`, SHA-256 `b3653029…e511`), and the second smoke run, with the pin, gave the
  same rates and token counts; the median latency per triage case was 2.7 s on one runner and 6.5 s on the
  other ([evidence note](evidence/2026-11-08-first-local-model-smoke.md)). Five easy items per set are not a
  rate.
- **Status (first full run, 2026-11-08):** the owner ran *Run workflow* on `main` (`f7d10f2`), both sets in
  full, in about 66 minutes (the build again, because the PR's cache belongs to its branch; `main` has its own
  now). Every item was answered (every triage case and topic step on the first attempt), and every code
  promise held. Triage: the rules' mistakes raised 32/32 (Typhoon 32/32), 3 needless raises (Typhoon 1), AI
  correct 58/61 (Typhoon 60/61). Study guide: topic correct 44/48 (Typhoon 46/48), all correct 61/67 (Typhoon 62/67), 0 of 142 links
  outside the library; one injection (`TH-ATK-02`) chose the topic it asked for, and the links still came
  only from the library. Median latency about 7 times Typhoon's API on both sets. One run on the developer's
  labels, so a first measurement of this file, not accuracy
  ([evidence note](evidence/2026-11-08-first-local-model-full.md)).
- **Done when:**
  - the smoke run on the PR answers through the whole path, in an evidence note;
  - the model file is pinned in the workflow (commit and SHA-256);
  - the first full run after the merge is in an evidence note, with every rate as numerator/denominator,
    the latency, the failures and the run time.
- **Owner test (ไทย):**
  1. เปิด GitHub → Actions → *Local open model eval* → Run workflow (ปล่อยค่าเดิม คือทั้ง 2 ชุด ทุกข้อ)
  2. รอจนเป็นสีเขียว เครื่องทดสอบคิดด้วย CPU จึงใช้เวลานานกว่ารอบของ Typhoon มาก (เวลาจริงจดไว้ในบันทึกหลักฐาน)
  3. กดเข้าไปดู Summary ต้องเห็น:
     - "ไฟล์โมเดล" บอกว่าตรึงไว้แล้ว และตรวจ SHA-256 แล้ว
     - "เครื่องรันโมเดล" กับ "ตรวจการเชื่อมต่อ AI" ที่ขึ้นว่า answered
     - ตารางคะแนน 2 ชุด พร้อมหมายเหตุว่าเป็นโมเดลเปิดที่รันเอง ไม่ใช่ Typhoon ผ่าน API และไม่ใช่ Claude
- **After the first full run** (the plan the owner asked for on 2026-11-08):
  1. **Read the results together.** An evidence note puts the rules, Typhoon's 30B through the API and the
     local 4B side by side. In shadow mode the AI decides nothing, so what matters most is how many of the
     rules' mistakes it raises for review (Typhoon: 32/32); then needless raises, off-format answers and
     latency. No target is set before the run (as in 0.3). Done on 2026-11-08:
     [evidence note](evidence/2026-11-08-first-local-model-full.md), section 5 (32/32 raised, 3 needless
     raises against Typhoon's 1, no off-format answer in triage or the topic step, about 7 times slower).
  2. **Choose a branch.**
     - Not good enough: Typhoon stays the measured model, nothing else changes, and the lane stays for later.
     - Close: try what still fits the 16 GB runner, such as a less compressed file of the same model or
       another Apache-2.0 model. Each is a new agent version, scored on the same sets and compared with
       `--compare-with`.
     - Good enough: step 3.
  3. **A standing measurement lane.** Run it next to Typhoon in 5.6 and 5.7: the same exam for two models,
     where the items they disagree on are the ones for a person to look at. Because the file is pinned, a
     change in Typhoon's numbers with no change in the local model's points at Typhoon, not at our code (the
     weekly drift check of 5.7). A weekly schedule is the owner's choice; it costs nothing on this public
     repository.
  4. **The online page (D7).** The page uses the mock today. Typhoon is free through 0.4, but what is typed
     goes to SCB 10X. The open model behind the page needs a paid machine with room for the model, which is
     the owner's choice (D7). Then the model server goes into the service's container (one machine,
     ADR-003) through `render.yaml`, and the latency is measured again on Render's CPUs.
  5. **Real data last (D4).** A model on a machine we control keeps case text away from AI companies, but
     only 7.1–7.3 and written consent (7.5) make real data acceptable.
- **Don't:**
  - present the local model's numbers as Typhoon's API or Claude's;
  - serve the web page from GitHub Actions: GitHub's terms allow hosted runners only for building, testing
    and publishing the project;
  - unpin the model file or llama.cpp to get the latest; a new file or commit is a new version with a new run;
  - send real data to it before D4.

### 5.9 Auto-approve limits: a simulated "send it myself" button (asked by the owner on 2026-11-11)

- **Why:** the owner asked to see the system's limits with public data that developers use to measure systems,
  and with hard tests, as if there were a button that approves a case on its own when the system is confident,
  not only "send to review". A real button would break rule 4 (and ADR-010), so the question is answered by a
  measurement that changes nothing (ADR-031).
- **Built (PR #66):**
  - `app/eval/golden/case_triage_autosend_hard_v1.json`: 128 adversarial cases (64 Thai, 64 English), committed
    before any model answered them; `needs_person` on 38 (steering or approval injections, security, legal and
    privacy, distress);
  - `app/eval/autosend_sim.py`: replays saved scorecard reports through four policies (`ai_high`, `agree`,
    `agree_high`, `strict`) and counts sends, wrong sends with a 95% upper bound, `needs_person` and injected
    cases let through, safe sends, per-category F1, Thai/English pairs and injected copies; it fails when a real
    job did not wait for a person, and no service module may import it;
  - the hard set's mock baseline in *Core logic tests* (`tests/baselines/autosend_hard_mock.json`), and the
    manual workflow *Auto-approve limits (open benchmarks + hard set)*;
  - [autosend_simulation.md](autosend_simulation.md), with a Thai overview.
- **Status (2026-11-11):** measured once with Typhoon on about 1,300 cases
  ([evidence note](evidence/2026-11-11-autosend-limits.md)). The AI's own confidence does not separate right
  from wrong answers, and no signal in the system says "a person must see this", so every policy lets such
  cases through.
- **Done when:** the simulation runs in CI with the mock, the first live run is in an evidence note, and the
  docs say plainly that the button exists on paper only. Done.
- **Owner test (ไทย):**
  1. เปิด GitHub → Actions → *Auto-approve limits (open benchmarks + hard set)* → Run workflow (ปล่อยค่าเดิม) แล้วกด Run
  2. รอราว 45–60 นาที แล้วเปิดหน้า Summary
  3. ต้องเห็นหัวข้อ "จำลองปุ่ม อนุมัติเอง" บรรทัด "ระบบจริงส่งให้คนตรวจ 100%" และตารางของแต่ละชุด
     ตัวเลขอาจต่างจากบันทึกหลักฐานเล็กน้อย เพราะ AI ที่ให้บริการออนไลน์ตอบไม่เหมือนเดิมทุกครั้ง
- **Don't:** wire any policy into the Runner, the API or the page; quote a hard-set case in a prompt; change a
  label to make a policy look better; present these rates as accuracy on real traffic.
- **What a real button would need** (owner decision D9, not planned): a confidence that can be checked (E5), a
  plain-code check that holds text that talks to the system, reviewer labels (2.8), and a new ADR that changes
  rule 4 for one narrow, undoable action.

## Phase 6 — Milestone E: agent patterns and MCP

### 6.1 Pattern A: a bounded read-only tool loop inside one step

- **How it works:** inside one agent, the AI may call whitelisted read-only tools, for example "search the
  resource library" or "read the frame".
  - At most `max_turns` calls, all within the step's `timeout_s`.
  - The whole loop counts as one attempt for retries.
  - The final output passes the same three validators.
- **Gateway:** it supports tool use without a forced `tool_choice`, because current Claude models reject
  forced tool choice.
- **Don't:** put tools with side effects in the loop (ADR-007).

### 6.2 Pattern B: planner → checked plan → linked job

- **How it works:**
  1. A planner step outputs a plan as JSON, made only of registered agents.
  2. The application checks it against the registry and the limits (steps, depth, time, tokens).
  3. Optionally, a person approves the plan first (`REVIEW_REQUIRED`).
  4. The application admits it as a new linked job.
- Every plan has a receipt.
- **Don't:** build pattern C (a DAG that changes shape inside Core).

### 6.3 MCP server

- **Tools:** `submit_job`, `get_job`, `list_jobs`, `get_status` and `list_frame`, over the HTTP API with a
  `submitter` token. **There are no review decisions**; those stay with people.
- **Transport:** standard-library JSON-RPC, over stdio first.
- **Why:** it lets Claude apps and other agents use the system.

---

## Phase 7 — Before other people, or a public repo

### 7.1 Mask personal data before AI calls; narrow key exposure (gap G5)

- **Redaction:** an application-layer step before every AI call.
  - It masks e-mail addresses, phone numbers (Thai formats), Thai 13-digit ID numbers, card-like numbers,
    and names where they can be detected.
  - The AI sees placeholders.
  - It is tested with Thai and English samples, and the redaction version is part of the agent version.
- **Key exposure:** today every Core worker inherits the same environment, so every worker can see
  `ANTHROPIC_API_KEY`. Find the smallest way to give the key only to AI steps. This may need a Core design
  note; do not change Core without an ADR.
- **Status (2026-11-03): masking built in PR #28; key exposure written up below, not built.**
  - `app/llm/redaction.py` masks e-mail addresses, phone numbers (Thai and `+` formats), Thai ID numbers
    (check digit verified), card-like numbers (Luhn), other runs of 9 or more digits (bank accounts and
    the like), and names after a title or a label (Mr/Ms/Dr, "my name is", `Name:`; นาย, นาง, นางสาว,
    น.ส., ด.ช., ด.ญ., นามสกุล, and คุณ + an English name). Thai digits count as digits.
  - The gateway accepts only text that went through `mask()`, so no AI call can skip it. The AI step
    records how many items of each kind it masked (never the values); the job view and the page show them.
  - The masking version (`redact-v1` then, `redact-v2` since 2026-11-10) is part of the AI agent's version and of the frozen job params, like the prompt hash:
    changing the rules is a new version, and an interrupted job fails as `configuration_changed`.
  - Not detected, and written in the module: names without a title or label (คุณสมชาย, where คุณ may also
    mean "you"), Thai surnames after a given name, a given name run into the next word, addresses, numbers
    of fewer than 9 digits, identifiers that mix letters and digits. Real data therefore still waits for
    D4, after 7.2 and 7.3; rule 9 in CLAUDE.md says so.
  - The scorecard's 61 synthetic cases contain nothing the rules mask; all 61 answers stay the same.
  - **Key exposure, design note.** Every process in the container runs as the same user, `neuron`, and
    inherits one environment: the HTTP API, the Runner and every Core worker. Any of them can read the
    key, from its own environment or from `/proc/<pid>/environ` of the others. Removing it from the API's
    `os.environ` would not help: `/proc/<pid>/environ` keeps the environment the process started with.
    Options, smallest first:
    1. Spend limit on the key (owner, D2): limits the damage of a leak; no code. Do it when the key is made.
    2. Per-agent environments in Core (worker pools that only pass the key to AI agents): a Core change
       that needs an ADR, and it would not protect the key from the API process, which runs as the same
       user.
    3. An AI broker process under its own user, the only holder of the key: AI agents send the masked
       request over a local socket and get the answer back; the API, the Runner and the workers never see
       the key. No Core change, but a second user in the image, a small protocol and its tests, and an
       ADR because it changes the process layout of ADR-014.

    Recommendation: 1 now (with D2), 3 before 7.2 or any real data. Until then, the only AI code is the
    trusted agents in this repository, and the service on Render runs the mock AI, which needs no key.
- **Status (2026-11-10): the gateway enforces the masking itself (ADR-028).** The independent review of that day
  (point 2) found that the gateway only checked the type of its input, which any code could build. Now:
  - only `mask()` can make a `MaskedText` (calling it directly raises `TypeError`; it is read-only and cannot be
    copied or pickled);
  - the gateway accepts only one made under the current rules, reads its text once, masks it again and refuses
    with `UnmaskedText` (nothing is sent) when the rules would still change anything;
  - a static test allows the networked providers only through the gateway, and checks that the connection
    probe sends nothing but its fixed synthetic sentence.
  - The re-check relies on "masking twice changes nothing", and testing it found that `redact-v1` broke it on
    44 of 300,000 random strings: `นางสาว` + a name was masked again as `นาง` + the "name" `สาว`, a name glued
    to an English title showed a second name, and a number glued to a name became a number. `redact-v2` runs
    the rules until nothing changes and never takes `สาว` after `นาง` for a name: 0 of 1.2 million random
    strings and of the 6,920 robustness strings change on a second pass. All 61 triage and 67 study answers
    and every robustness outcome stay the same.
- **Owner test (ไทย):**
  1. เปิดหน้าเว็บ พิมพ์เคส "อัปโหลดไฟล์แนบไม่ได้ ติดต่อกลับ 081-234-5678 หรือ somchai@example.com" แล้วกดยืนยัน
  2. เมื่อเคสขึ้น "รอคนตรวจ" ในรายละเอียดผลต้องมีแถว "ปิดข้อมูลส่วนตัวก่อนส่งให้ AI" ที่บอกว่า "อีเมล 1 · เบอร์โทร 1"
  3. ความเห็นของ AI จำลองยังต้องเป็น "อัปโหลดไฟล์" เพราะคำสำคัญไม่ถูกปิด
  4. กด "รายละเอียดเชิงเทคนิค" ต้องเห็น "กฎปิดข้อมูลส่วนตัว (redaction): redact-v2"

### 7.2 Production HTTP server and authentication hardening

- **Server:** when real traffic starts, replace `app/api/server.py` with a small WSGI adapter around
  `ApiApp`, served by a production server such as waitress. Keep the same routes and tests.
- **Authentication:** add token expiry, an audit log of owner actions, and per-token limits.

### 7.3 Independent security review (owner)

- Write a threat model in `docs/security.md`, then bring in an outside reviewer.
- Record the findings and the fixes, including the ones that were not fixed (funding M4).
- **Status (2026-11-10): a first independent review, not yet 7.3.** The owner brought in an outside reviewer
  who read the code and docs at `f38c926`, with a focus on data and security risks, and did not test the running
  service. Four findings, all answered the same day
  ([evidence](evidence/2026-11-10-independent-review-response.md)); D8 was then decided: keep the history. 7.3 still needs the
  threat model and a review that also tests the service.

### 7.4 Public-release checklist (owner decision D5)

- Move the Sentry DSN in `.github/workflows/sentry-smoke.yml` into a repository secret, or rotate it.
- Scan the whole git history for secrets, for example with gitleaks in CI.
- Confirm the rights to all code and history, and keep the GPL-3.0-only license.
- Disclose AI assistance where funders require it.
- Write a README section for outsiders.
- **Status (2026-11-03): the preparation is built in PR #29; publishing stays the owner's decision (D5).**
  - [x] The Sentry smoke workflow reads its DSN only from the repository secret `SENTRY_DSN`. Without it, a
    push skips the test with a notice and a manual run fails with the steps to add it.
  - [x] *Actions → Secret scan* runs gitleaks v8.30.1 (built from source, so the Go checksum database
    verifies it) over every commit of every branch on every push and pull request. The rules are gitleaks'
    defaults plus a Sentry DSN rule, which the defaults lack (`.github/gitleaks.toml`). A second pass
    without the reviewed list fails if an entry in `.github/.gitleaksignore` is no longer found.
  - [x] First scans (2026-11-03, all branches): the defaults found nothing; the DSN rule found one item,
    the old DSN added in commit `683f963`. It is listed in `.github/.gitleaksignore` with the reason.
  - [x] `tests/test_no_secrets.py` checks the files as they are now with the standard library, so a cloud
    session without gitleaks catches a pasted key before it is pushed.
  - [x] **Owner:** the DSN is in the repository secret `SENTRY_DSN` (the smoke test sent its event on
    2026-11-03).
  - [x] **Owner, before going public:** revoke the old DSN in Sentry (Settings → Client Keys), create a new
    one and put it in the secret, because the old one stays readable in the history. Done on 2026-11-08: a
    new client key is in the secret (the smoke test's events arrived in Sentry) and in Render, and the owner
    reported the old key disabled (it stays in Sentry's list of keys).
  - [x] **Owner, when going public:** turn on GitHub's secret scanning, push protection and private
    vulnerability reporting (free for public repositories); confirm the rights and the license. The AI
    disclosure and the README section for outsiders are done (PR #44). All three are on (checked through
    the API on 2026-11-08), and the owner published the repository under GPL-3.0-only.
- **Status (2026-11-08): ✅ public with its full history (D5)** (offered: a clean public copy, the full
  history, or a rewrite). The owner did the clicks below the same day.
  - Audit of everything that becomes public: 107 commits on every branch and the 43 pull-request refs (989
    blobs), 473 Actions runs and the current files. One secret: the old DSN, the "CI and development" client
    key, the only one of the project's 3 client keys that appears in the history. No other key.
  - Stays visible by the owner's choice: one of the owner's two personal e-mail addresses in the author or
    committer field of 51 commits (53 by 2026-11-10, because merges made on github.com still add it; see 7.6) (mostly merges made on github.com); 393 deleted files, mostly the earlier
    application's (the samples checked are synthetic); `docs/funding/`, which is marked internal. A rewrite
    would not hide them, because GitHub keeps the pull-request refs read-only.
  - [x] Deleted the 7 *Sentry smoke test* runs from before PR #29: their workflow used the old DSN as a
    fallback, so their logs could print it. Later runs read only the secret, and *Secret scan* runs with
    `--redact`.
  - [x] Every workflow's token is read-only and none uses `pull_request_target`
    (`tests/test_workflow_permissions.py`, PR #44).
  - [x] A README section for visitors with the AI-assistance disclosure, and `SECURITY.md` (PR #44).
  - [x] **Owner, before the switch:** replace the old DSN (owner test steps 1–5); delete the 8 merged branches,
    which hold no unmerged commit (this session's proxy refuses branch deletion), and turn on "Automatically
    delete head branches"; optionally keep new commits' e-mail private (GitHub Settings → Emails). Done: only `main` is left, and
    head branches are deleted automatically.
  - [x] **Owner, the switch (D5):** Settings → Danger Zone → Change visibility → Public. Public since
    2026-11-08: a request without a token sees the repository and its GPL-3.0 license.
- **Owner test (ไทย) — ขั้นตอนก่อนและหลังกดเปิดสาธารณะ:**
  1. **เปลี่ยนคีย์ Sentry:** เปิด Sentry → Settings → Projects → neuron-flow-runtime → Client Keys (DSN)
     → Generate New Key แล้วคัดลอกค่า DSN ของคีย์ใหม่
  2. GitHub → repo นี้ → Settings → Secrets and variables → Actions → แถว `SENTRY_DSN` กดรูปดินสอ วางค่าใหม่
     แล้วกด Update secret
  3. Render → neuron-flow → Environment: ถ้ามีแถว `SENTRY_DSN` ที่ค่าขึ้นต้นด้วย `https://c9fe6f2b` ให้แก้แถวนั้น
     เป็นค่าใหม่ อย่าแตะ `NEURON_FLOW_ACCESS_KEY` (ถ้ากด Save and deploy ระบบจะเริ่มใหม่ และเคสในคิวจะหาย)
  4. กลับไปที่ Sentry → Client Keys → คีย์ชื่อ "CI and development" → Disable หรือ Revoke
  5. GitHub → Actions → Sentry smoke test → Run workflow ต้องเป็นสีเขียว
  6. **ลบ branch เก่า:** เปิดหน้า Branches ของ repo แล้วกดรูปถังขยะของทุก branch ยกเว้น `main` (8 อัน)
  7. Settings → General → หัวข้อ Pull Requests → ติ๊ก "Automatically delete head branches"
  8. (ไม่บังคับ) รูปโปรไฟล์ GitHub → Settings → Emails → ติ๊ก "Keep my email addresses private" และ
     "Block command line pushes that expose my email" อีเมลใน commit เก่าจะยังอยู่ แต่ commit ใหม่จะไม่มี
  9. **กดเปิด:** Settings → General → Danger Zone → Change visibility → เลือก Public แล้วยืนยัน
  10. หลังเปิด: ในหมวด Security ของ Settings เปิด Secret scanning, Push protection และ Private vulnerability
      reporting แล้วเปิด Actions → Secret scan รันล่าสุด ต้องเป็นสีเขียว

### 7.5 Consented pilot with real volunteers (owner decision D4)

- **Only after 7.1–7.3,** with written consent, a disclosed task scope and approved data.
- **Never** use real customer tickets without permission.
- Results go to the evidence track, separate from synthetic numbers.

### 7.6 The personal e-mail address in the public history (owner decision D8)

- **Why:** the independent review of 2026-11-10 (point 1) rated it the highest risk. One of the owner's personal
  addresses is in the author or committer field of 53 commits on `main`: 51 when the repository went public on
  2026-11-08 (7.4 recorded that), and one more for each merge made on github.com since (PR #50 and #60), because
  GitHub uses the account's address for merges unless it is kept private. An address in a public repository can
  be collected for spam or phishing; anyone who copied the repository or its events since 2026-11-08 keeps it.
- **Built on 2026-11-10 (stops the count growing unnoticed):** the `commit-emails` job in *Secret scan*
  (`.github/scripts/check_commit_emails.py`). A pull request fails when one of its commits carries a personal
  address; a push only warns, because a red check on `main` would stop Render's deploy-after-checks; both runs
  report the count for the whole history. Addresses are never printed, only their domain.
- **Owner, now (one setting, stops new ones):** GitHub → Settings → Emails → "Keep my email addresses private"
  and "Block command line pushes that expose my email". Merges made on github.com then use the private
  `…@users.noreply.github.com` address. The next merge's *Secret scan* run shows no warning.
- **Owner decision D8, about the 53 commits already public.** A dry run on a local copy (2026-11-10; nothing was
  pushed) replaced the address in all 59 author and committer fields: every file in every commit stayed byte
  for byte the same, but every commit id changed, because the repository's first commit is one of them.
  1. **Keep the history as it is.** No work and nothing breaks. The address stays visible.
  2. **Rewrite the history and ask GitHub Support to purge the old commits.** A session replaces the address with
     the owner's private GitHub address, updates every commit id the docs and `.github/.gitleaksignore` quote in
     the same push, and force-pushes `main` (only with the owner's explicit permission: it rewrites the shared
     branch). Open pull requests must be opened again. The old commits stay reachable through the 50+ read-only
     pull-request refs until GitHub Support removes them, and Support decides whether it will.
  3. **Re-create the repository from the rewritten history.** Removes the pull-request refs without depending on
     Support, but loses the issues, pull requests, Actions history and settings; the repository secrets
     (`TYPHOON_API_KEY`, `SENTRY_DSN`) must be added again and Render connected to the new repository.

  **Decided (2026-11-10): option 1.** The owner said to leave the history as it is. No rewrite is planned.

  Neither 2 nor 3 reaches copies made since 2026-11-08. **Recommendation (before the decision):** the setting above now, then 1 unless
  the owner wants the address out of the public view; then 2, and 3 only if Support declines.
- **Owner test (ไทย):**
  1. คลิกรูปโปรไฟล์ GitHub มุมขวาบน → Settings → Emails
  2. ติ๊ก "Keep my email addresses private" และ "Block command line pushes that expose my email"
  3. ครั้งถัดไปที่กด Merge ให้เปิด Actions → Secret scan ของ commit นั้น → งาน commit-emails ต้องไม่มีคำเตือน และหน้าสรุปต้องบอกว่าในประวัติทั้งหมดยังเป็น 53 commit (ไม่เพิ่ม)

---

## Effectiveness track (E1–E6)

Added on 2026-11-10 (PR #50), because the owner asked for a plan to make the system more effective. The packages, their
reasons, tasks, checks and owner tests are in [effectiveness_plan.md](effectiveness_plan.md); their status is
in the table above. The baseline they start from is in
[an evidence note](evidence/2026-11-10-effectiveness-baseline.md).

- **What it follows:** eleven measures of what a person meets when using the system (M1 to M11 in the
  plan), with today's value for each; one, people's answers to "เข้าใจถูกไหม", is not recorded yet. A package
  that moves a measure writes the new value in an evidence note.
- **Order:** E3 is the owner's decision and needs no code, so it can happen at any time. E1, then E2, come
  before the next phase. E4 goes with Phase 2 or Phase 4, E5 after 5.6, and E6 when the owner has time to
  read the candidates. As with a phase, a package starts when the owner says so. On 2026-11-10 the owner
  said to plan the work and carry it out without asking first: E1 was built that day (PR #60), and E2
  follows it.
- **Phase 2 stays the largest step for effectiveness that is already planned:** until a reviewer can decide,
  a case cannot finish and there are no labels from a person (2.8, D6).
- **Not in it:** more workers or machines (the online service ran 3 jobs in 7 days, and a warm job takes
  0.1 to 0.4 s), making the AI's answer the official suggestion (ADR-010, D6), and targets set before a first
  measured run.
- **Paused (2026-11-11):** E4 and E6 belong to the study guide, which the owner paused; they wait until the
  owner resumes it.

---

## Skill handoff track (H1–H5)

Added on 2026-11-11, because the owner asked for skills that stay separate and pass work to each other through a
go-between, with a translator on the way that turns the data into the receiving agent's own language. The design,
its reasons, the alternatives and the done-when of each package are in [skill_handoff.md](skill_handoff.md); the
decision is ADR-030 (in force). Their status is in the table above. The same day the owner asked for it to be
built and shown working, and for it to be tested with a new suite and with the existing ones: H1–H3 and the page part
of H5 were built ([evidence](evidence/2026-11-11-skill-handoff.md)).

- **H1 The design and ADR-030.** This file's section, the design doc and the ADR. Done: the owner asked for it
  to be built.
- **H2 The common language and the first translators.** `app/exchange/` with the envelope, the vocabulary
  (`vocabulary_v1.json` and its complete SHA-256), the `Translator` type, `out.case_triage.v2@1` and
  `in.case_triage.v2.apply@1`, a static test that no skill imports another skill or the exchange, and tests that pin
  each translator's output. Built.
- **H3 The exchange and the first route.** The route table (`routes_v1.json`, its hash and checks), queue schema
  3 with the `handoffs` table and a tested upgrade, the handoff inside the Runner's and the reviews service's
  transactions, events, the job view's `handoff` field and the route list in `/v1/status`, and the first route:
  `case_triage.v2` `APPROVED` → `case_triage.v2.apply`, which is roadmap 2.3. Built; it meets the P0 gate
  "approval creates exactly one phase-B job". Checked in CI by `tests/test_service_handoff.py`, by
  `tests/handoff_check.py` over every case of the three triage sets, by the demo on the run page and by the
  container smoke test. Left: the owner's test on the live page after the merge.
- **H4 The first new skill**, chosen by the owner, built as its own domain and joined to the others only through
  translators and one route. An example to choose from: a reply draft for an approved case, which a person reads
  and nothing sends.
- **H5 The chain on the page and in traces:** "ส่งต่อจาก" and "ส่งต่อไปที่" in the Flow tab, a refused handoff's
  reason in Thai, what an approval will start on the decision card (built), and a link between the two jobs'
  traces (not built).
- **Order:** next, the owner's test of H3 on the live page after the merge; the trace link of H5 needs no owner
  decision; H4 when the owner has chosen. As with a phase, a package starts when the owner says so.
- **Don't:** let a skill import, call or name another skill; route on an `ai` fact; use AI as a translator; let
  an outside request name a route, a translator or a handoff; build conditions, fan-out or fan-in before a route
  needs them (each needs its own ADR); add a broker or a second process (ADR-003, P2).

---

## Not now (P2): do not build early

- Multi-tenancy, distributed workers or claims, Postgres, object storage, SLAs, a hosted dashboard
  (architecture.md §9).
- Pattern C: DAGs that change shape inside Core.
- Live step-by-step progress inside a running job. Core runs a job as one blocking loop; revisit this with
  tracing.
- Semantic (embedding) search for `CaseMemory` (gap G9). Build it only as a separate adapter in `app/`, and
  only if a feature needs it.

## Owner decisions

| ID | Decision | Needed before | Options | Until then |
|---|---|---|---|---|
| D1 | Pay for Render so cases survive restarts | 0.2; real use of Phase 2 | Free ($0, forgets cases) · `0.5c-512mb` + 1 GB disk (about $7.25 a month at Nov 2026 prices) | Free |
| D2 | Claude API key and monthly spend limit | 0.3 path B, 0.4 with Claude | Key as a GitHub secret and/or in Render's Environment tab; spend limit in the Claude Console | Typhoon (free, rate-limited) for live measurement; the mock everywhere else |
| D3 | Who reviews, and how they are told | 2.5 | Owner only · named reviewers; e-mail, LINE or Slack | Owner only, no notifications |
| D4 | Real data | 7.5 | Synthetic only · consented pilot | Synthetic only |
| D5 | Public repository and funding application | 7.4 | Stay private · publish an approved snapshot · publish this repository with its full history (chosen on 2026-11-08) | Public since 2026-11-08 |
| D6 | The AI's role in triage | after 2.8 has enough reviewed cases | Keep shadow mode · AI suggestion first, still with human review | Shadow mode (ADR-010) |
| D8 | The personal e-mail address in 53 public commits | — (the setting in 7.6 stops new ones now) | Keep the history (chosen by the owner on 2026-11-10) · rewrite it and ask GitHub Support to purge the old commits · re-create the repository from the rewritten history (7.6) | Decided: kept as it is; new commits checked in CI |
| D7 | An open model behind the online page | 5.8 step 4 | Mock (today) · Typhoon through 0.4 (free; what is typed goes to SCB 10X) · the local model on a paid machine with room for it (prices checked at the time) | The mock on the page; the local model only in GitHub Actions, for measuring |
| D9 | Sending a case without a person (an auto-approve button) | not planned; it would change rule 4 and ADR-010 | No (today) · a narrow trial for one low-risk action with undo, only after a confidence that can be checked (E5), a check for text that talks to the system, and reviewer labels (2.8); see 5.9 | Simulation only (ADR-031): every case waits for a person |

## Evidence track

- **Dated notes.** Every measured run (live Claude, a restore drill, a security review, a pilot) gets a
  note in `docs/evidence/YYYY-MM-DD-<topic>.md`, following [METRICS_PLAN.md](funding/METRICS_PLAN.md).
  Each note records:
  - the commit SHA, the CI or run link, the environment and the model;
  - every rate as numerator/denominator;
  - failures and exclusions.
- **Funding gates** ([funding/README.md](funding/README.md), "Next evidence gates"):
  - gate 2 → 0.3;
  - gate 3 → done (Milestone B);
  - gate 4 → 2.1–2.3 and 2.7, then 7.3;
  - gate 5 → 7.4;
  - gate 6 → 7.5.

## Risks to keep in mind

| Risk | What we do |
|---|---|
| The free plan forgets cases | The API and the page say so at every write, and the page counts what was lost after a wipe (ADR-029); D1 decides; Phase 2 needs the disk for real use |
| Personal data in the public history | The owner's address is in 53 commits; CI checks new commits; the owner's GitHub setting stops new merges adding it; D8 keeps the old history as it is (7.6) |
| One machine, one disk | Accepted (ADR-003, ADR-014); backups in 1.4; no scaling until a P2 item is justified |
| AI cost or outage | Spend limit (D2), queue cap, rate limits, a graceful "unavailable" (ADR-012) |
| A model is retired or changed | A new model is a new agent version: run the scorecard compare first and switch between runs. In-flight jobs fail as `configuration_changed`, by design |
| Prompt injection | Answers limited to fixed choices, validators, and injection test sets in every new domain |
| Made-up links in study guides | The AI never writes URLs; code inserts them from the verified library |
| Docs drifting from the code | The definition of done in CLAUDE.md, plus the checks in 1.5 |
| Hosting or connector changes | Keep the Dockerfile portable and `railway.json` kept; re-check connector tool lists before relying on them |
| A model file or llama.cpp changes upstream | Both pinned (commit, SHA-256); a new file is a new agent version (`<name>:<hash>`) with a new run (5.8) |

## Change log

- 2026-11-01: first version, written before development moved to Claude Code.
- 2026-11-03: added 1.6, the new look for the web page, because the owner asked for it with a design
  mockup; noted in 4.4 what the chat layout already covers.
- 2026-11-03: 1.6 marked done after the owner tested the new page on Render.
- 2026-11-03: 0.6 changed: the Dependabot PRs targeted removed files, so they were closed and replaced by
  one PR that moves the current workflows to the Node 24 action versions.
- 2026-11-03: 1.1 done in PR #21. Core now records each step under its step id; a test keeps catalog
  step ids away from Core's own phase names (`contract_validation`, `delivery`).
- 2026-11-03: 1.2 done in PR #22. Client ids that contain a job id or equal the access key are
  replaced too, so the access-line privacy rules hold.
- 2026-11-03: 1.3 done in PR #23. The page asks for a second click before it cancels, because a
  cancel cannot be undone; the 409 body names the current state as `job_status`.
- 2026-11-03: 1.5 done in PR #24. Besides links and the README count, the check also covers `#anchors`
  and the test count stated in CLAUDE.md, architecture.md, intake_queue.md and this file.
- 2026-11-03: status cleanup. 0.1, 0.5 and 0.6 marked done with evidence read from Render and CI
  (`docs/evidence/2026-11-03-render-operations.md`, which also carries the measurements from the closed
  PR #17). The owner summary got a status column.
- 2026-11-03: 5.3 done in PR #26. Besides the run time it shows the queue wait and how many jobs were
  taken over after a Runner stop, because both explain a slow maximum.
- 2026-11-03: 5.2 done in PR #27. The gate compares every per-case answer, not only the AI outcome, so a
  change to the rules turns it red too. The baseline lives in `tests/` to keep baseline-only merges from
  redeploying Render.
- 2026-11-03: 7.1 split. Masking is built in PR #28. Narrowing key exposure turned out to need either a
  Core change or a new process under its own user (both need an ADR), so it is written up as a design note
  in 7.1 and left for before 7.2.
- 2026-11-03: 7.4 preparation in PR #29: the DSN only from a secret, and a history scan in CI. gitleaks
  is built from source in CI, so the Go checksum database verifies it and no download hash is pinned; its
  defaults miss Sentry DSNs, so one rule was added. Publishing and the rest of the checklist stay with the
  owner (D5).
- 2026-11-03: 5.1 built in PR #30 with a small standard-library exporter instead of the OpenTelemetry SDK
  (ADR-017), and ticked after the first trace was seen in Honeycomb on Render. That check found that steps
  carried no agent version and that the key instructions were unclear; both were fixed in the follow-up PR.
- 2026-11-05: the owner chose Phase 3 before Phase 2. 3.1 done in PR #32: a summary per topic and `by`,
  `kind` and `access` per resource were added to the planned fields; the link check also runs on every
  change to the study guide, and treats moved and bot-blocked links as warnings, not failures. After a
  transient connection reset on its first run, it retries twice instead of once.
- 2026-11-05: 3.2 done in PR #33. "Thai first" became "the person's language first"; detection also
  returns the language; the final step's id is `answer`. Two decisions were written down: ADR-018
  (informational answers end without review) and ADR-019 (prompts completed from versioned data).
- 2026-11-06: 3.3 done in PR #34 with the mock. The scorecard also became an eval gate, and the gate's code
  is now shared with the triage scorecard (`app/eval/common.py`). The live Claude run waits for D2.
- 2026-11-06: the owner's Anthropic account asked for card verification, so 0.3 got a free path first:
  GitHub Models as a third provider (ADR-020), two manual workflows that use the workflow's own token, and
  pacing in both scorecards for the free tier's per-minute limit. Claude stays path B, waiting for D2.
- 2026-11-06: the first GitHub Models run (5 cases) finished, but the AI answered 0/5 (all "unavailable"),
  and the model catalog could not be parsed as JSON. Both workflows now check the connection with one fixed
  sentence first and show the raw reply, run pages count why the AI gave no answer, and replies with a
  leading byte-order mark are accepted. No result is recorded until a run answers.
- 2026-11-06: the connection check on the next run showed why: `HTTP 200`, `text/plain`, body `OK`. GitHub
  retired GitHub Models on 2026-07-30 (announced 2026-07-01), which the research for ADR-020 missed. The
  owner chose Typhoon instead and stored `TYPHOON_API_KEY`; ADR-021 replaces the GitHub Models provider and
  workflows with an OpenAI-format client and two Typhoon workflows. Lesson: check that a service is still
  running, from its own changelog, before building on it.
- 2026-11-06: the owner's first Typhoon run (5 cases) got HTTP 200 but plain `key: value` lines, so the AI
  answered 0/5: Typhoon ignores `response_format`. ADR-022 (PR #38): the client states the answer format in
  words and reads the one JSON object; the format version is part of the agent version. Then the full sets
  on the PR's branch: triage AI correct 60/61 in two runs (rules 29/61), study guide topic correct 46/48 with
  0 of 142 links outside the library; 0.3 path A is done ([evidence note](evidence/2026-11-06-first-live-typhoon.md)).
  The triage run page now also lists the AI's own mistakes, because this session cannot download a run's
  per-case report.
- 2026-11-07: 3.4 built in PR #39 (the owner asked to start it). A switch above the box chooses a case or a
  study question; a question is sent without the confirm card (ADR-023), because it decides nothing and its
  answer asks "เข้าใจถูกไหม". The layered answer also names the most important resource when the first one is
  background (first-response rule 4). 0.4 gained the free Typhoon option, because the owner test's metaphor
  needs a real model on the online page. Marked 🟡 until the owner tests it on the live page.
- 2026-11-07: Phase 5 gained 5.4–5.7, because the owner asked for a 3-stage benchmarking plan with open datasets and hard edge cases. 5.4 is built in PR #41: a robustness benchmark over 270 synthetic items and four open datasets, as a CI gate with a baseline that records failures too. Its first run found 8 bugs (two causes, both fixable outside Core), so 5.5 fixes them next. ADR-024 records which open data counts as synthetic (written for a dataset, openly licensed, no real people's records); ai4privacy was left out for its licence.
- 2026-11-08: 5.4 marked ✅ (PR #41 merged after the owner checked the run page). 5.5's 8 bugs fixed in PR #42, because the owner asked to start. Intake turns every parse failure and every input Core cannot store into 400, and the gateway cleans a lone surrogate in AI text to U+FFFD instead of refusing the answer as planned, so the case keeps the AI's second opinion. Correction: the stage-1 note said all 8 were fixable outside Core. Seven are; SYN-COR-040 tests Core's own `decode()`, so it needed a Core change, recorded as ADR-025 and kept as its own commit. Re-run: 215/270 pass, 0 bugs, 44 gaps (the gap SYN-COR-041 passes too). 5.5 stays 🟡 for the gap decisions.
- 2026-11-08: 3.4 marked ✅: the owner tried the study box on the live page with the mock AI (the example "รั้วกั้น AI" got the layered answer: a one-line summary, "เข้าใจถูกไหม", where to start, the most important resource, the study steps and the details). PR #42 merged; after its deploy the owner's case `WEB-261108-7C8Z` still reached review (rules and the mock AI disagreed, so it was escalated). The docs that still called both of them waiting now say they are done.
- 2026-11-08: 7.4: the owner chose D5 = publish this repository with its full history, from three options (a clean public copy, the full history, a rewrite; a rewrite cannot hide what GitHub's read-only pull-request refs keep). Everything that becomes public was audited; the 7 *Sentry smoke test* runs whose logs could print the old DSN were deleted; every workflow's token is now read-only, with a test; the README has a section for visitors with the AI-assistance disclosure, and `SECURITY.md` was added (PR #44). Left for the owner: replace the old DSN, delete the 8 merged branches, then the switch.
- 2026-11-08: 7.4 marked ✅ and D5 done: the owner replaced the Sentry DSN (a new key in the secret and in Render, the old key reported disabled), deleted the merged branches, turned on automatic branch deletion, switched the repository to public and turned on secret scanning, push protection and private vulnerability reporting. Checked through the GitHub API, the Render log and Sentry.
- 2026-11-10: the owner asked for an additional plan to make the system more effective (PR #50). Added the effectiveness track, E1 to E6 ([effectiveness_plan.md](effectiveness_plan.md)), with a baseline measured for it ([evidence note](evidence/2026-11-10-effectiveness-baseline.md)): the 116 edge cases with Typhoon for the first time, run from a cloud session (AI correct 104/116, rules 48/116; all 12 of the AI's mistakes are cases labelled `other`, and it said `high` confidence for all 116); the mock's longer keyword list scores 74/116 on that set, which it had not seen; and the first job after a start took 9.0 to 10.5 s in 4 of 4 observations, with a likely cause (the image has no bytecode cache, so each new worker process compiles what it imports). The plan leaves out more workers or machines, because the online service ran 3 jobs in 7 days. Nothing is built yet.
- 2026-11-10: E1 built (PR #60), because the owner asked to plan the work and carry it out without further questions. Its first task found more than the baseline had assumed: the service image had no bytecode cache at all, not for `app/` and `neuron_flow/` and not for the standard library (0 of the 141 modules the Runner imports), so every new process compiled everything it imported. The `Dockerfile` now compiles all of it once with hash-based cache files, and *Service container* fails when one is missing or does not match its source. Measured on GitHub's runners, one run each: the first case after a start 0.989 s before and 0.256 s after, and with the container held to 0.1 CPU 14.4 s before and 3.1 s after ([evidence note](evidence/2026-11-10-e1-bytecode-cache.md)). E1 stays 🟡 until the time on Render is measured after the merge. E2 is next.
- 2026-11-10: the first independent review of the code and docs (at `f38c926`) found four problems; all four are
  answered in one pull request ([evidence](evidence/2026-11-10-independent-review-response.md)). 2.2 and 2.4 were
  built before 2.1 (ADR-027) so a person can close a case; the gateway now enforces the masking (ADR-028,
  `redact-v2`); retention is stated at every write and lost cases are counted (ADR-029); new commits are checked
  for personal e-mail addresses, and 7.6 with owner decision D8 was added for the ones already public. The
  owner asked for every point to be fixed, which is also the go-ahead to start Phase 2.
- 2026-11-11: the owner paused new work on the study guide (Phase 3, E4 and E6; what is built stays, and its
  checks keep running) and asked for skills that stay separate and pass work through a go-between, with a
  translator on the way into each agent's own language. Added the skill handoff track, H1 to H5
  ([skill_handoff.md](skill_handoff.md), ADR-030 proposed). The design uses one common language with a translator
  on each side instead of one translator per pair (10 translators instead of 20 for 5 skills), and makes 2.3's
  linked job after an approval the first route, so the exchange is tried on planned work before the first new
  skill.
- 2026-11-11: the owner asked for the exchange to be built rather than only designed ("I want to see it work"), and
  then for a test suite and a run against the existing suites. H1–H3 and H5's page part were built in the same pull
  request: `app/exchange/`, the route-only `case_triage.v2.apply` (2.3), queue schema 3 with a `handoffs` ledger,
  the handoff in the decision's own transaction, the API fields and the page. Tests: 37 new (448 in all), a
  case-set check over all 217 existing triage cases, a step-by-step demo on the run page and new checks in the
  container smoke test; every earlier gate unchanged. The check first lived in `app/eval/`, and the guard that only
  the API records decisions inside `app/` refused it, so it moved to `tests/handoff_check.py`. Also recorded: PR
  #64 (E2) was merged on 2026-11-11; the docs still said it was waiting.
- 2026-11-11: the owner asked to see the system's limits with public benchmark data and hard tests, simulating a
  button that approves a case on its own when the system is confident. Added 5.9 and ADR-031: the button exists on
  paper only (a replay of saved answers; the service cannot import it, and the replay fails if a real job did not
  wait for a person). Built with it: 5.6's open benchmarks (CLINC150, BANKING77, MASSIVE th/en pairs; BIPIA's attacks
  as 5.7's first injection data, because `deepset` is only on Hugging Face), a 128-case hard set committed before
  any model saw it, and owner decision D9. Measured once with Typhoon; the session paused for the owner's credits
  after the first six sets, and BANKING77, which the pause interrupted, was run again in full.
