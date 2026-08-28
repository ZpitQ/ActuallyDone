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

`pom.xml` 声明了 JaCoCo，但没绑生命周期。门禁步骤必须是
`mvn -B -ntp jacoco:prepare-agent test jacoco:report`，否则报告读不到。

本机第一次 `adone gate run`（adone 1.3.8）：12 通过 / 覆盖率 97.0%，回执全绿。
覆盖率下限已回填为 90（实测水位，不是许愿）。验收契约在 `adone/acceptance/`。
