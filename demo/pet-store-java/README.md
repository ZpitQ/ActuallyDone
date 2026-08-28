# pet-store-java

ActuallyDone 的 Java 演示项目：内存宠物店，Spring Boot 3.3 + Maven，不引数据库。

## 业务

- `GET /pets` / `GET /pets/{id}`
- `POST /pets` 登记（拒绝空名、未知物种、负价格）
- `POST /pets/{id}/buy` 售出（已售出再买返回 409）

物种只认 `cat` / `dog` / `bird` / `fish`。

## 自己跑

需要 JDK 17 和 Maven。

```bash
cd demo/pet-store-java
mvn -B -ntp test
mvn -B spring-boot:run    # http://localhost:8080/pets
```

## 用 adone 复核「做完了」

在本目录（不要在 ActuallyDone 仓库根）：

```bash
adone init --yes
adone install --with-hooks
adone gate run
adone gate check
```

`pom.xml` 声明了 JaCoCo，但没绑生命周期。门禁步骤必须带
`jacoco:prepare-agent` … `jacoco:report`，否则报告读不到。

## UT 按本机核数并行

JUnit 5 用 `dynamic` 策略，线程池 = `availableProcessors() × factor`（这里 factor=2）。
类和方法都 `concurrent`。这些开关写在门禁 `argv` 的 `-D` 上，由
`.adone/policy-baseline.json` 锁住：改命令等于改判据，要
`adone policy --accept "理由"`。

`pom.xml` 只负责把同名 Maven 属性转进测试 JVM（Surefire 的 `-Dparallel` 只认 JUnit 4，
不要用 `-DargLine=…`，会盖掉 JaCoCo 探针）。

`PetControllerTest` 用 `@WebMvcTest` 切片（不要全量 `@SpringBootTest` +
`@DirtiesContext` 逐条重启，否则墙钟几乎全耗在起上下文上），用例互不依赖
id=1 / 空列表，才能和 `PetStoreTest` 一起并行。

```bash
adone policy --accept "门禁改为 JUnit 5 按本机核数并行跑 UT"
adone gate run
```

本机第一次 `adone gate run`（adone 1.3.8）：12 通过 / 覆盖率 97.0%，回执全绿。
覆盖率下限已回填为 90（实测水位，不是许愿）。验收契约在 `adone/acceptance/`。
