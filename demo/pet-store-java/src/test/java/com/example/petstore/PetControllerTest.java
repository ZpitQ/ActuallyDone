package com.example.petstore;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

@WebMvcTest(PetController.class)
@Import({PetStore.class, ApiExceptionHandler.class})
@Execution(ExecutionMode.CONCURRENT)
class PetControllerTest {

    private static final ObjectMapper JSON = new ObjectMapper();

    @Autowired
    private MockMvc mvc;

    @Test
    void listIncludesCreatedPet() throws Exception {
        String name = "Listed-" + UUID.randomUUID();
        mvc.perform(post("/pets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(petJson(name, "cat", "12.5")))
                .andExpect(status().isOk());

        mvc.perform(get("/pets"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[?(@.name == '" + name + "')]").exists());
    }

    @Test
    void createThenGetPet() throws Exception {
        MvcResult created = mvc.perform(post("/pets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(petJson("Mochi-" + UUID.randomUUID(), "cat", "12.5")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").isNumber())
                .andExpect(jsonPath("$.status").value("AVAILABLE"))
                .andReturn();
        long id = idOf(created);

        mvc.perform(get("/pets/" + id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.species").value("cat"));
    }

    @Test
    void createRejectsNegativePrice() throws Exception {
        mvc.perform(post("/pets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(petJson("Nemo-" + UUID.randomUUID(), "fish", "-1")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("price must not be negative"));
    }

    @Test
    void buyThenRejectSecondBuy() throws Exception {
        MvcResult created = mvc.perform(post("/pets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(petJson("Kiwi-" + UUID.randomUUID(), "bird", "20")))
                .andExpect(status().isOk())
                .andReturn();
        long id = idOf(created);

        mvc.perform(post("/pets/" + id + "/buy"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SOLD"));

        mvc.perform(post("/pets/" + id + "/buy"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error").value("pet already sold: " + id));
    }

    @Test
    void getMissingPet() throws Exception {
        mvc.perform(get("/pets/99"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("pet not found: 99"));
    }

    private static String petJson(String name, String species, String price) {
        return "{\"name\":\"" + name + "\",\"species\":\"" + species + "\",\"price\":" + price + "}";
    }

    private static long idOf(MvcResult result) throws Exception {
        JsonNode body = JSON.readTree(result.getResponse().getContentAsString());
        return body.get("id").asLong();
    }
}
