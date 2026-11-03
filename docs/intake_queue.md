# Intake API, job queue, Runner and web page (round 2, Milestone B)

**Status:** built in PR #11 and tested offline (169 tests on 2026-11-03, including killing the Runner
mid-step). The container build is checked on every push by *Actions → Service container*. Live on
Render's free plan since 2026-11-01 (`render.yaml`). Railway was the first choice, but it has paused new
sign-ups since 22 Oct 2026 after a security incident; `railway.json` stays in the repository for later.
Synthetic data only. Review decisions (approve/reject) come with Milestone C, so in this round every case
ends at "waiting for a person". No Core (`neuron_flow/`) file was changed.
The web page was redesigned on 2026-11-03 (PR #18, roadmap 1.6) after the owner's "Nocturne" mockup: a
chat-style intake with a confirm step, a Flow panel and an event history (Trace), and read-only settings
(see "หน้าเว็บ: ใช้อย่างไร" and "Web page" below). It is live on Render, and the owner reported that the
owner test passed on the live page the same day.
Queue and run-time figures (roadmap 5.3, PR #26): `GET /v1/status` and the page show how many cases wait,
how long the oldest has waited, the median and slowest wait and run times per workflow over the newest 100
finished jobs, and failures by reason (see "ตัวเลขคิวและเวลา" and "Queue and run-time figures" below).
Tracing (roadmap 5.1, PR #30): with `HONEYCOMB_API_KEY` set, every `/v1` request and every job become spans
in Honeycomb, one trace per job ([observability_tracing.md](observability_tracing.md)).
Design principles: [design_philosophy.md](design_philosophy.md).

## ภาพรวมการทำงาน (ภาษาไทย)

### เมื่อมีคนส่งเคส 1 เคส ระบบทำอะไรบ้าง

1. **ส่งเคส** ผ่านหน้าเว็บ หรือผ่าน API (`POST /v1/jobs`) พร้อม "รหัสส่งงาน" (idempotency key) หนึ่งรหัสต่อการกดส่งหนึ่งครั้ง หน้าเว็บสร้างรหัสนี้ให้เอง
2. **ตรวจก่อนรับ** ระบบตรวจรหัสเข้าใช้ ขนาดคำขอ และข้อมูลเคส (รหัสเคส + ข้อความ 8–500 ตัวอักษร) ถ้าไม่ผ่าน ระบบตอบกลับทันทีและยังไม่สร้างงานใด ๆ
3. **บันทึกลงคิวถาวรก่อนตอบ** ระบบตอบว่า "รับแล้ว" (202) หลังบันทึกเสร็จเท่านั้น
   - ส่งซ้ำด้วยรหัสส่งงานเดิมและข้อความเดิม → ได้งานเดิมกลับมา (200) ไม่เกิดงานซ้ำ
   - รหัสส่งงานเดิมแต่ข้อความต่าง → ปฏิเสธ (409)
4. **ตัวรันงานมีตัวเดียว** หยิบงานตามลำดับที่เข้ามา บันทึก "สเปกงาน" ฉบับที่จะใช้จริงไว้ก่อน แล้วจึงส่งให้แกนระบบ (Core)
5. **Core ทำงานทีละขั้นเหมือนรอบ 1** กฎเดิมกับ AI ทำคู่กัน → เทียบสองความเห็น → เตรียมข้อเสนอ และตรวจผลทุกขั้นก่อนบันทึก
6. **บันทึกผล** สถานะสุดท้ายคือ "รอคนตรวจ" (`REVIEW_REQUIRED`) พร้อมสรุปที่อ่านง่าย ไม่มีที่อยู่ไฟล์ภายในหรือรหัสลับ
7. **ดูผล** หน้าเว็บอัปเดตเอง หรือเรียก `GET /v1/jobs/{job_id}`

### ถ้ามีอะไรผิดพลาด

| เหตุการณ์ | ระบบทำอะไร | คุณเห็นอะไรบนหน้าเว็บ |
|---|---|---|
| ข้อความสั้นหรือยาวเกิน ข้อมูลเกินที่กำหนด | ปฏิเสธทันที ไม่สร้างงาน (400) | ข้อความเตือนใต้ฟอร์ม |
| กดส่งซ้ำ หรือเน็ตหลุดแล้วส่งใหม่ | ใช้งานเดิม (200) | "ระบบรู้ว่าเป็นเคสเดิม จึงไม่สร้างงานใหม่" |
| เครื่องดับหรือรีสตาร์ทกลางงาน | เปิดใหม่แล้วทำต่อ นับครั้งที่ลองตามงบเดิมของขั้นนั้น | เคสเดินต่อ ในรายละเอียดเห็น "ตัวรันงานหยิบเคสนี้ 2 ครั้ง" |
| งบลองใหม่ของขั้นนั้นหมดแล้ว | หยุดเคสนั้นพร้อมเหตุผล ไม่รันเกินงบ | "ไม่สำเร็จ" และหมายเหตุ "ตัวรันงานหยุดกลางคัน" |
| เปลี่ยนรุ่น AI หรือ prompt ระหว่างที่เคสค้างอยู่ | ไม่รันต่อด้วยค่าใหม่โดยไม่บอก | "ตั้งค่า AI หรือ prompt ถูกเปลี่ยนหลังรับเคส" |
| เคสเดิมทำให้ตัวรันงานล่มซ้ำ 3 ครั้ง | พักเคสนั้นไว้ เพื่อไม่ให้วนล่มไม่จบ | "ตัวรันงานหยุดกลางคันระหว่างทำเคสนี้หลายครั้ง" |
| ตัวรันงานล่ม | ตัวเปิดระบบเปิดตัวรันงานใหม่ให้ใน 1–30 วินาที ระหว่างนั้นยังรับเคสเข้าคิวได้ | ป้าย "ตัวรันงาน: ไม่ตอบ" ชั่วคราว |
| ตั้งค่า AI ไม่ครบ (เช่น เลือก Claude แต่ไม่ใส่ key) | ไม่เริ่มงานใด ๆ เคสรอในคิวจนกว่าจะแก้ | แถบเตือนสีเหลืองบอกสาเหตุ |
| คิวเต็ม หรือส่งถี่เกินไป | ปฏิเสธชั่วคราว (503 / 429) | "คิวเต็ม" หรือ "ส่งถี่เกินไป รอ N วินาที" |
| ใส่รหัสเข้าใช้ผิด 10 ครั้งในหนึ่งนาที | พักการลองจากเครื่องนั้นชั่วคราว (429) | "ลองรหัสผิดหลายครั้งเกินไป" |

**ตามรอยคำขอ (request id)** ทุกคำตอบจากระบบมี "รหัสคำขอ" ติดมาด้วย (หัวข้อ `X-Request-Id`) รหัสเดียวกันนี้อยู่ในบันทึกการเข้าใช้ (access log) และในเหตุการณ์แรกของงาน ("รับเข้าคิว") เมื่อมีปัญหา ให้เปิดเคสนั้น → "รายละเอียดเชิงเทคนิค" → ดู "รหัสคำขอที่ส่งเคสนี้" แล้วส่งรหัสนี้ให้ Claude ไล่ดูใน log ได้ตรงคำขอนั้นทันที ถ้าระบบขัดข้องฝั่งเซิร์ฟเวอร์ ข้อความเตือนบนหน้าเว็บก็จะบอกรหัสคำขอด้วย รหัสนี้ไม่มีข้อความเคสหรือรหัสลับ

ทุกกรณีที่ระบบกู้งานหลังตัวรันงานหยุด จะส่งแจ้งเตือนเข้า Sentry ด้วย (ถ้าตั้งค่า `SENTRY_DSN` ไว้) ดู [observability_sentry.md](observability_sentry.md)

### หน้าเว็บ: ใช้อย่างไร

หน้าจอแบ่งเป็น 3 ส่วน (บนมือถือ ส่วนซ้ายกับขวาซ่อนไว้ กดปุ่ม ☰ หรือแถบขั้นตอนใต้หัวเพื่อเปิด)

| ส่วน | มีอะไร |
|---|---|
| ซ้าย | ปุ่ม "＋ เคสใหม่", จำนวนเคสตามสถานะ (เมื่อมีเคสรอ จะบอกด้วยว่าเคสที่รอนานสุดรอมานานเท่าไร), รายการเคสล่าสุด (วันนี้ / เมื่อวาน), สถานะ AI ที่เก็บข้อมูล ตัวรันงาน และ "เวลาต่อเคส" (ปกติใช้เวลาเท่าไร), ปุ่ม "ล็อกหน้าจอ" |
| กลาง (แท็บ "แชท") | ช่องพิมพ์เคส และบทสนทนาของเคสที่เลือก: ข้อความเคส → การ์ดขั้นตอน → ผลที่ระบบเสนอ |
| ขวา ("Flow") | แผนผังขั้นตอนของเคส (เส้นบอกว่าขั้นไหนต้องรอขั้นไหน) และ "ประวัติเหตุการณ์ (Trace)" ของเคสนั้น |

ลำดับการใช้งาน:
1. **พิมพ์เคส** ปัญหาของลูกค้าเป็นภาษาธรรมดาในช่องด้านล่าง (หรือกดตัวอย่าง) แล้วกด Enter หรือปุ่ม "ส่ง" (Shift+Enter = ขึ้นบรรทัดใหม่) อยากตั้งรหัสเคสเองให้กด "# รหัสเคส" ไม่ใส่ระบบตั้งให้
2. **ดูก่อนส่ง** ระบบยังไม่ส่ง แต่แสดงการ์ด "รอยืนยัน" ว่าจะทำขั้นตอนอะไรบ้าง แต่ละขั้นรอได้นานเท่าไร และลองได้กี่ครั้ง
3. **ยืนยัน** กด "ยืนยันและส่ง" เคสจึงเข้าคิว ("แก้ข้อความ" เอาข้อความกลับไปแก้, "ยกเลิก" ทิ้งร่างนี้)
4. **เปลี่ยนใจก่อนเริ่มทำ** ระหว่างที่เคสยัง "รอคิว" จะมีปุ่ม "ยกเลิกเคสนี้" กดแล้วระบบถามยืนยันอีกครั้ง ("ยืนยันยกเลิก" หรือ "ไม่ยกเลิก") เพราะยกเลิกแล้วเอาคืนไม่ได้ เคสที่ยกเลิกจะขึ้น "ยกเลิกแล้ว" ไม่มีขั้นไหนถูกรัน และ AI ไม่ได้เห็นเคสนั้น ถ้าตัวรันงานหยิบเคสไปทำแล้ว ปุ่มจะหายไป (แกนระบบหยุดงานกลางทางไม่ได้) ถ้าต้องการส่งเคสเดิมอีก ให้ส่งเป็นเคสใหม่
5. **ระหว่างทำงาน** หน้าเว็บบอกว่า "กำลังทำงาน" ทั้งเคส เพราะแกนระบบ (Core) ยังไม่ส่งความคืบหน้าทีละขั้น เมื่อเสร็จ ทุกขั้นจะขึ้น ✓ หรือ ✕ พร้อมจำนวนครั้งที่ลอง
6. **อ่านผล** ระบบเสนอคิวไหน ความสำคัญ ความเห็นของกฎและของ AI และเหตุผลที่บอกคนตรวจ ผลสุดท้ายคือ "รอคนตรวจ" เสมอ แถว "ปิดข้อมูลส่วนตัวก่อนส่งให้ AI" บอกว่าระบบปิดอะไรไปกี่จุดก่อน AI อ่าน (ขั้น 7.1)
7. **กลับมาดูทีหลัง** ลิงก์ในแถบที่อยู่มีรหัสงาน (`#job_…`) เปิดลิงก์เดิมจะกลับมาที่เคสนั้น (ถ้าเคสยังไม่ถูกล้าง)

แท็บ "ตั้งค่า" **ดูอย่างเดียว**: ขั้นตอนและตัวทำงาน (agent) ของแต่ละประเภทงาน, AI ที่ใช้อยู่และวิธีเปลี่ยนใน Render, กติกาการตัดสิน, ที่เก็บข้อมูลและขีดจำกัด, "ตัวเลขการทำงาน" (ดูหัวข้อถัดไป) และ "เส้นทางงานใน Honeycomb" (เปิดหรือปิด ส่งไปที่ไหน การส่งล่าสุดสำเร็จไหม และวิธีเปิดใน Render ดู [observability_tracing.md](observability_tracing.md)) เมื่อเปิดส่งเส้นทางงานแล้ว "รายละเอียดเชิงเทคนิค" ของแต่ละเคสจะมี "รหัสเส้นทางใน Honeycomb (trace id)" ด้วย หน้าเว็บแก้ค่าเหล่านี้ไม่ได้โดยตั้งใจ: คีย์อยู่ใน Render เท่านั้น ตัวทำงานเปลี่ยนได้ผ่าน PR เท่านั้น และคนต้องเป็นผู้ตัดสินเสมอ

### ตัวเลขคิวและเวลา (ขั้น 5.3)

ระบบนับตัวเลขเหล่านี้ใหม่ทุกครั้งที่หน้าเว็บถามสถานะ (ทุก 4 วินาที) จากคิวงานโดยตรง จึงไม่ต้องเก็บอะไรเพิ่ม

| ตัวเลข | ความหมาย | ดูได้ที่ |
|---|---|---|
| รอคิวตอนนี้ | มีกี่เคสที่ยังรอตัวรันงาน และเคสที่รอนานสุดรอมานานเท่าไร | ซ้าย ใต้จำนวนเคส (ขึ้นเมื่อมีเคสรอ) และแท็บ "ตั้งค่า" |
| เวลารอคิว | ตั้งแต่รับเข้าคิวจนตัวรันงานหยิบไปทำ | แท็บ "ตั้งค่า" |
| เวลาทำงาน | ตั้งแต่ตัวรันงานหยิบไปทำจนได้ผล นับเคสที่ไม่สำเร็จด้วย | ซ้าย ("เวลาต่อเคส" ของงานแบบที่หน้าเว็บใช้) และแท็บ "ตั้งค่า" |
| ปกติ / นานสุด | "ปกติ" คือค่ากลาง (median) ครึ่งหนึ่งของเคสใช้เวลาไม่เกินนี้ "นานสุด" คือเคสที่ช้าที่สุด | แท็บ "ตั้งค่า" แยกตามประเภทงาน |
| หยุดกลางคัน | เคสที่ตัวรันงานหยุดระหว่างทำ แล้วตัวใหม่ทำต่อ เวลาทำงานของเคสนั้นรวมช่วงที่รอตัวใหม่ด้วย | แท็บ "ตั้งค่า" |
| สาเหตุที่ไม่สำเร็จ | นับตามสาเหตุ เช่น "มีขั้นตอนที่ไม่สำเร็จ" หรือ "ตั้งค่าเปลี่ยนหลังรับเคส" | แท็บ "ตั้งค่า" |

ข้อควรรู้:
- นับจาก 100 เคสล่าสุดที่ทำจบเท่านั้น เคสที่ยกเลิกไม่นับ เพราะไม่ได้รัน
- แผนฟรีของ Render ล้างคิวทุกครั้งที่ระบบหลับ รีสตาร์ท หรืออัปเดต ตัวเลขจึงเริ่มนับใหม่ทุกครั้ง
- ตัวเลขมีแค่เวลา จำนวน ชื่อประเภทงาน และรหัสสาเหตุ ไม่มีข้อความเคสหรือรหัสงาน
- ตอนนี้ระบบใช้ AI จำลอง เวลาที่เห็นจึงยังไม่ใช่เวลาของ Claude จริง

ส่วนที่อยู่ในแบบ (mockup) แต่ยังไม่มีในระบบ:
- ช่องคุยถาม-ตอบทั่วไป และคำสั่ง `/test` `/eval` `/backup` → ขั้น 4 และ 1.4 ในแผน (ตอนนี้ช่องแชทรับเฉพาะข้อความเคส)
- ไฟบอกว่ากำลังทำขั้นไหนระหว่างรัน → ยังไม่อยู่ในแผนตอนนี้ (P2) จะพิจารณาอีกครั้งพร้อมระบบติดตามเส้นทางงาน (ขั้น 5)
- ปุ่มหยุดงานที่กำลังทำอยู่ → ทำไม่ได้ เพราะแกนระบบหยุดงานกลางทางไม่ได้ (ยกเลิกได้เฉพาะเคสที่ยังรอคิว ทำแล้วในขั้น 1.3), ปุ่มอนุมัติ/ไม่อนุมัติ → ขั้น 2.4
- ช่องใส่ API key, เปลี่ยน AI, ตั้งจำนวนครั้งลองใหม่, ตัวเลือก "ไม่ต้องถาม" และปุ่ม "แก้ไข JSON" → จะไม่ทำ เพราะขัดกฎของโปรเจกต์ (CLAUDE.md ข้อ 4–7)

### สิ่งที่ต้องทำเพื่อเปิดใช้บน Render (ครั้งแรก ทำครั้งเดียว)

ไฟล์ `render.yaml` ในโปรเจกต์บอก Render ไว้หมดแล้วว่าต้องสร้างอะไร คุณจึงแค่กดยืนยัน

1. **Merge PR นี้** เข้า `main` (Render จะดึงโค้ดจาก `main`)
2. **สมัคร Render** ที่ render.com ด้วยบัญชี GitHub แผนฟรีไม่ต้องใช้บัตร
3. **สร้างจาก Blueprint** ในหน้า Dashboard กด New → Blueprint → Connect GitHub แล้วอนุญาตให้ Render เห็น repo `System_Neuron_flow_AI` → เลือก repo นี้ Render จะแสดงว่าจะสร้างบริการ `neuron-flow` แผน Free ที่ Singapore → กด **Deploy Blueprint**
4. **รอ build** ประมาณ 3–5 นาที จนสถานะเป็น Live
5. **คัดลอกรหัสเข้าใช้** เปิดบริการ `neuron-flow` → แท็บ Environment → ค่าของ `NEURON_FLOW_ACCESS_KEY` (Render สุ่มให้แล้ว) เก็บไว้ อย่าแชร์
6. **ลองใช้** เปิดลิงก์ `https://neuron-flow….onrender.com` ที่หัวหน้าบริการ ใส่รหัสเข้าใช้ แล้วส่งเคสแรก
7. **เชื่อมตัวเชื่อม Render ใน claude.ai** (ไม่บังคับแต่แนะนำ) แล้ว Claude จะดูสถานะการ deploy, log และการใช้ทรัพยากรให้ได้ ตัวเชื่อมสร้างบริการแบบ Docker ได้ก็จริง แต่ตั้ง health check การรอให้ชุดทดสอบผ่านก่อน deploy การสุ่มรหัสเข้าใช้ และดิสก์ไม่ได้ จึงควรสร้างจาก Blueprint ในขั้นที่ 3 (กดเองครั้งเดียว)

หลังจากนี้ ทุกครั้งที่มีการ merge เข้า `main` และชุดทดสอบบน GitHub ผ่าน Render จะอัปเดตระบบให้เอง ยกเว้นเมื่อแก้แค่เอกสาร ชุดทดสอบ หรือไฟล์ตั้งค่า GitHub Actions Render จะไม่อัปเดตระบบ (ตั้งไว้ใน `buildFilter` ของ `render.yaml`) เคสในคิวจึงไม่หายเพราะการแก้เอกสาร

**แผนฟรีควรรู้:** ระบบหลับเมื่อไม่มีคนเข้า 15 นาที เปิดครั้งถัดไปรอประมาณ 1 นาที และไม่มีดิสก์ถาวร เคสเก่าจึงหายทุกครั้งที่ระบบหลับ รีสตาร์ท หรืออัปเดต (หน้าเว็บจะขึ้นป้ายเตือน) ระบบยังทำงานครบทุกขั้นตามปกติ

**ถ้าอยากให้เคสไม่หาย:** แผน `0.5c-512mb` ($7/เดือน) + ดิสก์ 1 GB ($0.25/เดือน) ต้องผูกบัตร บอก Claude ให้แก้ `render.yaml` (เปลี่ยนแผน เปิดดิสก์ที่ `/var/data` และตั้ง `NEURON_FLOW_DATA_DIR`) แล้ว merge ห้ามแก้แผนในหน้า Dashboard เพราะ Blueprint จะเขียนทับค่าที่ขัดกับไฟล์

ไม่บังคับ (เพิ่มในแท็บ Environment ได้เลย Blueprint จะไม่ลบตัวแปรที่ไฟล์ไม่ได้กำหนด):
- ใช้ Claude จริงแทน AI จำลอง: เพิ่ม `NEURON_FLOW_LLM_PROVIDER=anthropic` และ `ANTHROPIC_API_KEY` (เสียค่า API ประมาณ 1 คำขอสั้น ๆ ต่อเคส)
- แจ้งเตือนข้อผิดพลาด: เพิ่ม `SENTRY_DSN`

## How it works

### Processes and data

```text
browser / n8n / curl
      │  HTTPS (Render's edge)
      ▼
container: app.boot (root) ─becomes─► tini ─► python -m app.serve
                                               ├─ HTTP API + web page (app/api, app/web) ── admits, reads ──► <data>/app/queue.sqlite3
                                               └─ Runner child process (app/services/runner.py), restarted with back-off if it exits
                                                    ├─ claims jobs, freezes specs, records results and a heartbeat in queue.sqlite3
                                                    └─ the only owner of Runtime(<data>/core): Core SQLite, reports, workspace lock
```

- `<data>` is `NEURON_FLOW_DATA_DIR` (on Render, the disk's mount path), else Railway's
  `RAILWAY_VOLUME_MOUNT_PATH`, else `./neuron_workspace` (not persistent in a container).
- The container starts as root only to take ownership of the disk (hosts may mount it as root).
  `app/boot.py` (process 1) does that, switches to the unprivileged `neuron` user, then replaces itself
  with tini (same process, now `neuron`). tini, the launcher and the Runner all run as `neuron`, and
  nothing opens the data as root.
- tini must not stay root. On Render, root in the container may not signal another user's processes (no
  `CAP_KILL`). A root tini therefore could not pass SIGTERM on to the launcher: it logged
  `[FATAL tini (1)] Unexpected error when forwarding signal: 'Operation not permitted'` and exited, and the
  service was killed instead of stopped on every deploy, restart and sleep (seen on 2026-11-01; fixed by
  `app/boot.py`). Since the fix, stops on Render log `serve: stopping` and no FATAL line
  ([evidence](evidence/2026-11-03-render-operations.md)). The *Service container* job runs the image with
  `--cap-drop KILL`, checks that process 1 runs as `neuron`, and fails unless both its restart and its stop
  are graceful.
- The API never opens the Core `Runtime` (ADR-001). A disk attaches to one instance only, and a service
  with a disk cannot scale out, so two Runners never share it. Without a disk (Render's free plan) each
  instance has its own throwaway data, so an overlapping deploy cannot share anything either.

### Web page

- **Files:** `app/web/index.html`, `app.css`, `app.js`. Plain HTML, CSS and JavaScript: no build step, no
  framework, no external files. The look follows the owner's "Nocturne" mockup (claude.ai design export,
  2026-11-02): a dark blue-grey ground, one blurple accent used as lines and glow, outlined buttons.
- **Layout:** case list (left), chat thread and composer (middle), Flow graph and Trace (right). Below
  1200 px the Flow panel becomes a drawer; below 900 px the case list becomes a drawer, the Flow panel a
  bottom sheet, and a strip of steps sits under the header. The settings tab hides the Flow panel.
- **Data:** only the `/v1` routes. The confirm card and the Flow graph read the step plan from
  `GET /v1/status` (`workflows[].steps`, built once from the catalog with a placeholder case, never
  admitted) and, once the Runner has claimed a job, the plan frozen with that job (`plan` in
  `GET /v1/jobs/{job_id}`). Step results come from `result.steps`; the Trace from `/events`.
- **Honesty:** Core runs a job as one blocking loop, so a `RUNNING` job is shown as running as a whole;
  each step's ✓/✕ and attempt count appear when the job finishes. Nothing is animated per step.
- **Confirm step:** client-side. Nothing is sent before "ยืนยันและส่ง". The idempotency key is made with the
  draft, so "ส่งอีกครั้ง" after a network error cannot create a second job. "ส่งซ้ำ (ทดสอบว่าไม่เกิดงานซ้ำ)"
  stays on the last case sent from the tab.
- **Settings are read-only by design:** no field accepts a key, a provider, a retry budget or a policy
  (CLAUDE.md rules 4–7). The page explains where each value is changed instead. The tracing panel
  (roadmap 5.1) shows `status.tracing`: on or off with the reason, the destination host, the last export
  and its counts; it is redrawn with the metrics panel when only its figures change. A finished case's
  technical details show its `trace_id` when it has one.
- **Content-Security-Policy:** unchanged. No inline script, no style attribute; server data is inserted as
  text. The textarea height and the graph's edges are set through the DOM (CSSOM properties, SVG
  attributes), which the policy allows. No web fonts: the page uses the system's Inter/Thai fonts if
  present.
- **Links:** the selected job is kept in the URL fragment (`#job_…`), so a reload or a copied link reopens it.
- **How it was checked (2026-11-03):** a headless-browser walkthrough of every state on desktop
  (1280 and 1440 px), tablet (1024 px) and phone (390 px): no console errors, no CSP violations, no
  horizontal overflow; keyboard sending, focus moves, drawers with Escape, the error paths (short text, bad
  case id, wrong key) and "send again" returning the same job.

### Job states

```text
QUEUED ──► RUNNING ──► REVIEW_REQUIRED      the proposal waits for a person (every case_triage job)
   │              ├──► COMPLETED            a workflow without a review step
   │              ├──► FAILED               see failure.reason
   │              └──► DELIVERY_FAILED      all steps done, but the report conflicted with an existing one
   └──► CANCELLED                           withdrawn before the Runner claimed it; never reached Core
```

`CANCELLED` (roadmap 1.3) is reachable only from `QUEUED`. The check and the update run in one
`BEGIN IMMEDIATE` transaction, the same lock `claim_next` takes, so a claim and a cancel of the same job can
never both win. A cancelled job keeps its idempotency key: sending the same submission again returns the
cancelled job, not a new one. The `job.cancelled` event stores the request id of the cancel request. Core
cannot pause or stop a running job, so `RUNNING` jobs cannot be cancelled.

`failure.reason` is one of `step_failed`, `configuration_changed`, `runner_attempts_exhausted`,
`runtime_error`, `delivery_failed`, `unknown_workflow_type`.

### Recovery rules (the Runner at start-up)

For every job the queue still shows as `RUNNING`:
1. `claims >= NEURON_FLOW_MAX_CLAIMS` (default 3) → `FAILED: runner_attempts_exhausted`.
2. The spec the current settings would build differs from the spec frozen at the first claim → `FAILED:
   configuration_changed`. The job is never finished silently under another model, prompt or code version.
3. Otherwise the frozen spec is submitted again (Core treats an identical spec as a no-op) and run. Core
   marks the interrupted step `ControllerInterrupted` and retries it only if the step has attempts left.
   If Core had already finished the job before the crash, its saved result is used and nothing runs again.

In `case_triage.v2` only the AI step has a second attempt; the rule, compare and prepare steps take
milliseconds and have one. A planned stop is graceful: tini passes SIGTERM on to the launcher, which
passes it to the Runner, and the Runner finishes its current job first. The host waits 30 seconds before
it stops the container (Render's default, which its free plan does not let `render.yaml` change;
`drainingSeconds` in `railway.json`). The launcher gives the Runner 25 of those seconds.

## API reference

Every `/v1` route needs `Authorization: Bearer <NEURON_FLOW_ACCESS_KEY>`. Bodies are JSON, at most 16 KiB.

**Request ids (roadmap 1.2).** Every response, including the page, `/healthz` and errors refused before the
app runs, carries an `X-Request-Id` header:
- a client may send its own `X-Request-Id`: 1–64 characters, starting with a letter or digit, then letters,
  digits, `.`, `_` or `-`. It is used as is;
- anything else is replaced by a new id `req_<16 hex>`. That includes an id containing a job id (access
  lines never carry job ids) and an id equal to the access key;
- the id is the last field of the access log line, and a new job stores it in its first event
  (`job.queued`, `payload.request_id`). `GET /v1/jobs/{job_id}` returns it as `request_id` (`null` for jobs
  admitted before this change). A duplicate submission gets its own new id in the header, while the job
  keeps the id of the request that created it;
- a `500 internal_error` body also includes `request_id`.

| Method and path | What it does | Success | Errors |
|---|---|---|---|
| `GET /healthz` | Liveness for the host's health check (no key); also says whether an access key is set | 200 `{"ok": true, "access_key": "configured"}` | 503 |
| `GET /v1/status` | Runner heartbeat, queue counts, queue and run-time figures (`metrics`, below), AI mode, tracing (`tracing`: on or off and why, where spans go, the last export), storage, limits, and each workflow's steps (`workflows[].steps`) | 200 | 401, 429 |
| `POST /v1/jobs` | Admit a job | 202 new, 200 duplicate | 400, 401, 409, 411, 413, 415, 429, 503 |
| `GET /v1/jobs?limit=20&before=<seq>` | Newest first; `next_before` is the next cursor | 200 | 400, 401 |
| `GET /v1/jobs/{job_id}` | Status, the step plan frozen at claim (`plan`, `null` while queued), reviewer proposal, step timeline, AI provenance, receipt hash, the admitting `request_id`, and `trace_id` (the job's trace in Honeycomb; `null` when tracing was off) | 200 | 401, 404 |
| `GET /v1/jobs/{job_id}/events?after=<seq>&limit=50` | History in bounded pages (`limit` 1–100) | 200 | 400, 401, 404 |
| `POST /v1/jobs/{job_id}/cancel` | Withdraw a job that is still `QUEUED`. The body is empty or `{}`. Returns the job view plus `changed` (`false` when it was already cancelled) | 200 | 400, 401, 404, 409 `not_cancellable` (with `job_status`), 415 |

```bash
curl -s https://<your-service>.onrender.com/v1/jobs \
  -H "Authorization: Bearer $NEURON_FLOW_ACCESS_KEY" -H "Content-Type: application/json" \
  -d '{"workflow_type": "case_triage.v2", "idempotency_key": "n8n-2026-11-01-0001",
       "input": {"case_id": "CASE-001", "summary": "อัปโหลดไฟล์แนบไม่ได้ ค้างที่ 99%"}}'
# 202 {"job_id": "job_…", "status": "QUEUED", "queue_position": 1, "created": true, …}
```

- `workflow_type`: `case_triage.v2` (shadow mode, used by the page) or `case_triage.v1` (rules only).
- `idempotency_key`: 8–128 characters `[A-Za-z0-9._:-]`. Use one key per real submission and reuse it
  only to retry that submission.
- A request never carries agent names, import paths, steps, params or callbacks.
- A step plan (in `workflows[].steps` and `plan`) is a list of
  `{"id", "agent", "depends_on", "max_attempts", "timeout_s"}`, with Core's defaults filled in (5 seconds,
  2 attempts). It is read-only and never includes params.

Error bodies look like `{"error": "<code>", "message": "<English text>"}`. Codes: `invalid_fields`,
`invalid_json`, `unknown_workflow_type`, `invalid_idempotency_key`, `invalid_input`,
`idempotency_conflict` (with the existing `job_id`), `queue_full`, `rate_limited` and
`too_many_attempts` (with `retry_after_s` and a `Retry-After` header), `unauthorized`,
`access_key_not_configured`, `body_too_large`, `unsupported_media_type`, `length_required`,
`invalid_parameter`, `job_not_found`, `not_cancellable`, `method_not_allowed`, `not_found`, `internal_error`.

### Queue and run-time figures (roadmap 5.3)

`GET /v1/status` includes `metrics`, computed from the queue database on each request
(`app/services/metrics.py`; no extra state). Its shape, with made-up values:

```json
"metrics": {
  "waiting": {"count": 1, "oldest_age_s": 12.0},
  "window": {"limit": 100, "jobs": 4},
  "workflows": {"case_triage.v2": {"jobs": 4, "recovered": 1,
                                   "wait_s": {"median": 1.0, "max": 2.0},
                                   "run_s": {"median": 1.5, "max": 16.0}}},
  "failures": {"step_failed": 1}
}
```

- `waiting`: jobs still `QUEUED`, and the age of the oldest in seconds (`null` when none wait).
- `window`: the figures below cover the newest `limit` jobs (by admission order) that ran to an outcome
  (`REVIEW_REQUIRED`, `COMPLETED`, `FAILED`, `DELIVERY_FAILED`). Cancelled jobs never ran and are left out.
- `workflows`, per workflow type: `jobs` in the window; `wait_s` (admitted → first claim) and `run_s`
  (first claim → outcome) as median and maximum, rounded to milliseconds (`null` without values);
  `recovered`, the jobs a new Runner took over after a stop. Their `run_s` includes the time until the take-over.
  Failed jobs count, because they ran.
- `failures`: the window's `FAILED` and `DELIVERY_FAILED` jobs by `failure.reason` (`unknown` if none was
  recorded), the most frequent first, ties in name order.
- Privacy: timings, workflow names, counts and reason codes only; no case text, case ids or job ids.
- Cost: two small read-only queries per request. The window query walks the table backwards by `seq`
  (`NOT INDEXED`) and stops after `limit` rows, instead of sorting every finished job.
- On Render's free plan the queue, and so every figure, starts again after each sleep, restart and deploy.
- Tests: `tests/test_service_metrics.py` (hand-checked medians and maxima, the window, ordering, a clock that
  stepped back, and a real run through the Runner with no case text or ids in the figures).

## What proves it (P0 gates for Milestone B)

| Gate (docs/architecture.md §9) | Test |
|---|---|
| Concurrent identical requests produce one job; a mismatched payload is a conflict | `test_service_api`: `test_concurrent_identical_requests_create_exactly_one_job`, `test_concurrent_mismatched_requests_get_conflicts_not_new_jobs` |
| Admission stays responsive while jobs run | `test_service_runner`: `test_admission_stays_responsive_while_a_job_runs` |
| Only one Runner holds the lock | `test_only_one_runner_can_own_the_workspace` |
| Killing the Runner mid-step reconciles within the retry budget | `test_a_runner_killed_mid_step_is_recovered_within_the_retry_budget`, `test_no_retry_budget_left_means_a_clear_failure` |
| Invalid input is rejected before any agent runs | `test_invalid_requests_are_refused_before_any_job_exists` |
| A failed validator blocks only the dependent steps | `test_a_failed_validator_blocks_only_the_steps_that_depend_on_it` |
| Delivery conflicts get their own status | `test_a_delivery_conflict_gets_its_own_status` |
| Changed settings never finish an interrupted job silently | `test_changed_ai_settings_never_finish_an_interrupted_job_silently` |
| One request can be followed from the access line to the job record; unsafe client ids are replaced and never logged (roadmap 1.2) | `test_service_http`: `test_request_id_round_trips_and_follows_a_job`, `test_every_response_gets_a_fresh_id_when_none_is_sent`, `test_unsafe_request_ids_are_replaced_and_never_logged` |
| A queued job can be withdrawn; a claim and a cancel never both win; a cancelled job never reaches Core (roadmap 1.3) | `test_service_api.CancelTests` (6 tests, including 150 claim-versus-cancel races) |
| The access key never appears in responses, stored files or logs | `test_the_key_is_never_in_a_response_or_a_stored_file`, `test_the_service_starts_works_and_stops_cleanly`, CI container job |
| The container runs without root, keeps data across a restart and stops cleanly | *Actions → Service container* (`examples/service_smoke_test.py`) |

The review-related P0 gates (one decision per version, unauthorised reviews denied, exactly one phase-B
job) belong to Milestone C and are still open.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `NEURON_FLOW_ACCESS_KEY` | none (the API refuses `/v1`) | Shared access key, at least 16 characters |
| `NEURON_FLOW_DATA_DIR` | Railway volume, else `./neuron_workspace` | Where the queue and Core data live; on Render, the disk's mount path (`/var/data`) |
| `PORT` / `NEURON_FLOW_HOST` | `8000` / `0.0.0.0` | Listening address |
| `NEURON_FLOW_LLM_PROVIDER`, `NEURON_FLOW_LLM_MODEL`, `ANTHROPIC_API_KEY` | `mock` | AI second opinion (see [case_triage_v2_shadow.md](case_triage_v2_shadow.md)) |
| `NEURON_FLOW_MAX_QUEUED` | `100` | Admission refuses new jobs above this many waiting |
| `NEURON_FLOW_SUBMIT_PER_MINUTE` | `30` | Submissions per client per minute (4× for everyone together) |
| `NEURON_FLOW_MAX_CONNECTIONS` | `32` | Concurrent HTTP connections |
| `NEURON_FLOW_RUNNER_WORKERS` | `2` | Core child processes |
| `NEURON_FLOW_MAX_CLAIMS` | `3` | Runner stops tolerated per job before it is failed |
| `SENTRY_DSN` | none | Error reporting (optional) |
| `HONEYCOMB_API_KEY`, `HONEYCOMB_API_ENDPOINT`, `NEURON_FLOW_TRACING` | none (tracing off), US endpoint, on | Tracing (optional; see [observability_tracing.md](observability_tracing.md)) |

## Security notes

- One shared access key, compared in constant time, sent as a bearer token. The page keeps it in the
  browser (session storage, or local storage when "remember" is ticked). There are no per-person accounts
  yet; Milestone C adds reviewer identity.
- Ten wrong keys in a minute from one client pause that client's attempts.
- The page loads nothing from other sites and allows no inline script or style attribute (strict
  Content-Security-Policy). Server data is always inserted as text. The API sends no CORS headers.
- The settings view only displays configuration. No key, provider or limit can be set from the page, and
  keys never pass through it.
- Body cap (16 KiB, checked before reading), connection cap, socket timeouts, queue cap and rate limits.
- Logs, Sentry events and trace spans carry no case text, no query strings, no job ids in access lines and
  never a key. Spans name routes by template (`/v1/jobs/{job_id}`), never by the path a client sent. Responses carry no file paths. A client's `X-Request-Id` reaches the log only when it matches the
  safe pattern above and is neither a job id nor the key.
- Data is synthetic. Personal data is masked before the AI call (roadmap 7.1; what is and is not detected
  is listed in [case_triage_v2_shadow.md](case_triage_v2_shadow.md)), but the masking is pattern-based, so do
  not enter real customer information.

## Limits

- The HTTP server is Python's standard library server with the guards above. It suits a single-owner
  pilot; for real traffic, replace `app/api/server.py` with a production server (for example a small
  WSGI adapter around `ApiApp`, served by waitress or gunicorn).
- One machine, SQLite, one Runner (ADR-003). With a disk, each redeploy has a short downtime while the
  disk moves to the new instance. On Render's free plan the service sleeps after 15 idle minutes and
  forgets its cases.
- Rate limits live in memory and reset on restart.
- Live progress inside a running job is not shown step by step: the Flow panel shows the job as running,
  then every step's result when it finishes. Jobs with the mock AI finish in well under a second once the
  service is warm. On Render's free plan the first job after a start took 9–10 s (two starts measured on
  2026-11-01), later ones 0.1–0.4 s.
- The chat box takes case text only. Plain-language conversation (the router) is roadmap Phase 4.
- Review decisions, the n8n intake and reviewer notifications are Milestone C.
